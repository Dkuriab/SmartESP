"""Сквозной тест: поддельная колонка по WebSocket → ядро с подделками → звук ответа."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from core_harness import eventually, fake_kinds, make_core
from starlette.testclient import TestClient, WebSocketTestSession

from fakes.fake_connection import FakeConnection
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.contracts import (
    Annotation,
    ChatMessage,
    Delivery,
    Executor,
    Handoff,
    ReplyPart,
    ToolSpec,
    Utterance,
)
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub
from smartesp.wiring import Assembly

FRAME = bytes(1024)  # кадр колонки: 512 отсчётов s16le
RECEIVE_TIMEOUT_S = 5.0  # больше любого шага теста: тест не висит, даже если ядро молчит
MAX_FRAMES = 200  # ответ из теста заведомо короче


def _read(ws: WebSocketTestSession, timeout: float) -> dict[str, Any] | None:
    """Кадр от ядра или None, если за timeout ничего не пришло (receive TestClient'а ждёт вечно)."""
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["message"] = ws.receive()
        except BaseException as error:  # передаём в тест любую ошибку чтения
            box["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None  # поток дочитает при закрытии сессии и завершится
    if "error" in box:
        raise box["error"]
    return box["message"]


def receive(ws: WebSocketTestSession, timeout: float = RECEIVE_TIMEOUT_S) -> dict[str, Any]:
    """Ждёт кадр от ядра не дольше timeout; не пришёл — тест падает."""
    message = _read(ws, timeout)
    if message is None:
        pytest.fail(f"ядро ничего не прислало за {timeout} с")
    return message


def receive_json(ws: WebSocketTestSession) -> dict[str, Any]:
    """Ждёт текстовое сообщение протокола и разбирает его."""
    message = receive(ws)
    assert message.get("text") is not None, message
    return json.loads(message["text"])


def receive_reply(ws: WebSocketTestSession, turn: int) -> tuple[list[dict[str, Any]], bytes]:
    """Читает кадры до reply_end хода turn: текстовые сообщения и весь звук."""
    texts: list[dict[str, Any]] = []
    audio = bytearray()
    for _ in range(MAX_FRAMES):
        message = receive(ws)
        assert message["type"] == "websocket.send", message
        if message.get("bytes") is not None:
            audio += message["bytes"]
            continue
        data = json.loads(message["text"])
        texts.append(data)
        if data == {"type": "reply_end", "turn": turn}:
            return texts, bytes(audio)
    pytest.fail(f"нет reply_end за {MAX_FRAMES} кадров")


def ask(ws: WebSocketTestSession, turn: int) -> None:
    """Колонка: слово пробуждения, 10 кадров речи, пауза дольше окна арбитра, конец реплики."""
    ws.send_json({"type": "wake", "turn": turn, "level": -30})
    for _ in range(10):
        ws.send_bytes(FRAME)
    time.sleep(0.35)
    ws.send_json({"type": "utterance_end", "turn": turn, "reason": "vad"})


KITCHEN = "AA:BB:CC:DD:EE:01"
BEDROOM = "AA:BB:CC:DD:EE:02"


CONFIG_YAML = f"""
devices:
  kitchen: {{name: Кухня}}
  "{KITCHEN}": {{name: Кухня}}
  "{BEDROOM}": {{name: Спальня}}
stages: []
"""


@contextmanager
def running_core(
    home: Path, executor: Executor, tts: FakeTTS | None = None
) -> Iterator[tuple[TestClient, Assembly]]:
    """Ядро на подделках под TestClient (с lifespan: прогрев в фоне); ждём состояния ready."""
    core = make_core(home, fake_kinds(lambda c: executor, tts=tts or FakeTTS()), CONFIG_YAML)
    with TestClient(core.app) as client:
        deadline = time.monotonic() + RECEIVE_TIMEOUT_S
        while core.core.state != "ready":
            assert time.monotonic() < deadline, "ядро не прогрелось"
            time.sleep(0.01)
        yield client, core


HELLO = {"type": "hello", "device_id": "kitchen", "fw": "2.0", "protocol": 2}


def test_question_gets_spoken_reply(tmp_path: Path) -> None:
    executor = FakeExecutor(["Сейчас полдень."])
    with running_core(tmp_path, executor) as (client, _), client.websocket_connect("/device") as ws:
        ws.send_json(HELLO)
        ask(ws, 1)
        texts, audio = receive_reply(ws, 1)

    assert texts == [{"type": "reply_start", "turn": 1}, {"type": "reply_end", "turn": 1}]
    assert len(audio) > 0
    assert executor.calls[0][-1].content.endswith("сколько времени")


def test_disconnect_mid_reply_is_quiet(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    long_answer = [f"Предложение номер {i}. " for i in range(40)]
    executor = FakeExecutor(long_answer, delay=0.02)
    # короткий звук: ответ длится ~0,8 с из-за исполнителя, а не из-за темпа отправки
    with running_core(tmp_path, executor, FakeTTS(bytes_per_char=32)) as (client, core):
        with client.websocket_connect("/device") as ws:
            ws.send_json(HELLO)
            ask(ws, 1)
            assert json.loads(receive(ws)["text"]) == {"type": "reply_start", "turn": 1}
            assert receive(ws).get("bytes")  # пошёл звук — рвём связь посреди ответа
        hub = core.hub
        deadline = time.monotonic() + RECEIVE_TIMEOUT_S
        while hub.is_active("kitchen", 1) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not hub.is_active("kitchen", 1)

        # ядро живо: колонка переподключилась и получает ответ на новый вопрос
        with client.websocket_connect("/device") as ws:
            ws.send_json(HELLO)
            ask(ws, 2)
            texts, audio = receive_reply(ws, 2)
        assert texts[0] == {"type": "reply_start", "turn": 2}
        assert len(audio) > 0

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == []
    assert any("disconnected" in r.getMessage() for r in caplog.records)


def hello(device_id: str) -> dict[str, Any]:
    return {"type": "hello", "device_id": device_id, "fw": "2.0", "protocol": 2}


def test_two_speakers_louder_one_answers(tmp_path: Path) -> None:
    # номера ходов колонок (5 и 9) не совпадают с номерами хаба (1, 2…): путаница номеров видна
    executor = FakeExecutor(["Сейчас полдень."])
    with (
        running_core(tmp_path, executor) as (client, _),
        client.websocket_connect("/device") as quiet,
        client.websocket_connect("/device") as loud,
    ):
        quiet.send_json(hello(KITCHEN))
        loud.send_json(hello(BEDROOM))
        quiet.send_json({"type": "wake", "turn": 5, "level": -40})
        loud.send_json({"type": "wake", "turn": 9, "level": -25})
        for _ in range(10):
            quiet.send_bytes(FRAME)
            loud.send_bytes(FRAME)
        time.sleep(0.35)  # дольше окна арбитра
        quiet.send_json({"type": "utterance_end", "turn": 5, "reason": "vad"})
        loud.send_json({"type": "utterance_end", "turn": 9, "reason": "vad"})

        assert receive_json(quiet) == {"type": "cancel_turn", "turn": 5}
        texts, audio = receive_reply(loud, 9)
        assert texts == [{"type": "reply_start", "turn": 9}, {"type": "reply_end", "turn": 9}]
        assert len(audio) > 0
        assert _read(quiet, 0.3) is None  # тихой колонке больше ничего: ни reply_start, ни звука

    assert len(executor.calls) == 1
    assert "Колонка: Спальня" in executor.calls[0][-1].content


class _LateNetwork:
    """Сеть исполнителей: «Минутку…», передача большой модели, её ответ — только после gate."""

    def __init__(self) -> None:
        self.id = "dispatcher"
        self.gate = asyncio.Event()

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        yield ReplyPart("Минутку, сейчас узнаю.")
        yield ReplyPart(handoff=Handoff("dispatcher", "big", "Большая модель", "сложный вопрос"))
        await self.gate.wait()
        yield ReplyPart("Ответ сорок два.")


class _HubAnnouncer:
    """Простейшая очередь объявлений поверх хаба: синтез ядром и announce (настоящая — модуль notify)."""

    def __init__(self, hub: DeviceHub, speak: Callable[[str], AsyncIterator[bytes]]) -> None:
        self._hub = hub
        self._speak = speak
        self.results: list[Delivery] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def say(self, device_id: str, text: str, source: str) -> None:
        task = asyncio.create_task(self._deliver(device_id, text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, device_id: str, text: str) -> None:
        self.results.append(await self._hub.announce(device_id, self._speak(text)))


async def _no_annotations(utterance: Utterance) -> list[Annotation]:
    return []


async def test_end_to_end_late_answer() -> None:
    # колонка v3: ответ не успел → «долго думает» → ответ объявлен на ту же колонку
    hub = DeviceHub(0.02, 0.2, {"kitchen": "Кухня"})
    network = _LateNetwork()
    orchestrator = Orchestrator(
        hub,
        FakeSTT("сложный вопрос"),
        _no_annotations,
        network,
        FakeTTS(bytes_per_char=32),
        History(10, 600),
        thinking_interval_s=0.05,
        delegate_limit_s=0.2,
    )
    announcer = _HubAnnouncer(hub, orchestrator.speech)
    orchestrator.use_announcer(announcer)
    conn = FakeConnection()
    tasks = [asyncio.create_task(hub.handle(conn)), asyncio.create_task(orchestrator.run())]
    try:
        conn.feed_json("hello", fw="3.0", device_id="kitchen", protocol=3)
        await eventually(lambda: hub.supports_proactive("kitchen"))
        conn.feed_json("wake", turn=1, level=-30.0)
        for _ in range(5):
            conn.feed(FRAME)
        conn.feed_json("utterance_end", turn=1, reason="vad")
        await eventually(lambda: {"type": "reply_end", "turn": 1} in conn.sent_json())
        reply_audio = conn.sent_audio()
        assert len(reply_audio) > 0  # «Минутку…» и «Большая модель долго думает…»
        conn.feed_json("playback_done", turn=1)

        network.gate.set()
        core_turn = 0x80000001
        await eventually(lambda: {"type": "reply_end", "turn": core_turn} in conn.sent_json())
        frames = [m for m in conn.sent_json() if m.get("turn") == core_turn or m["type"] == "tone"]
        assert frames[-3:] == [  # сигнал «внимание» колонка играет сама, tone ядро не шлёт
            {"type": "announce", "turn": core_turn},
            {"type": "reply_start", "turn": core_turn},
            {"type": "reply_end", "turn": core_turn},
        ]
        assert len(conn.sent_audio()) > len(reply_audio)  # «Большая модель отвечает: …»
        conn.feed_json("playback_done", turn=core_turn)
        await eventually(lambda: announcer.results == ["delivered"])
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await hub.aclose()
