"""Сквозной тест: поддельная колонка по WebSocket → ядро с подделками → звук ответа."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import pytest
from starlette.testclient import TestClient, WebSocketTestSession

from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.config import Config, DeviceConfig
from smartesp.contracts import Executor
from smartesp.main import build_app

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


def make_client(executor: Executor) -> TestClient:
    config = Config(
        devices={
            "kitchen": DeviceConfig(name="Кухня"),
            KITCHEN: DeviceConfig(name="Кухня"),
            BEDROOM: DeviceConfig(name="Спальня"),
        }
    )
    app = build_app(config, FakeSTT("сколько времени"), FakeTTS(), executor, [])
    return TestClient(app)


HELLO = {"type": "hello", "device_id": "kitchen", "fw": "2.0", "protocol": 2}


def test_question_gets_spoken_reply() -> None:
    executor = FakeExecutor(["Сейчас полдень."])
    with make_client(executor) as client, client.websocket_connect("/device") as ws:
        ws.send_json(HELLO)
        ask(ws, 1)
        texts, audio = receive_reply(ws, 1)

    assert texts == [{"type": "reply_start", "turn": 1}, {"type": "reply_end", "turn": 1}]
    assert len(audio) > 0
    assert executor.calls[0][-1].content.endswith("сколько времени")


def test_disconnect_mid_reply_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    long_answer = [f"Предложение номер {i}. " for i in range(40)]
    executor = FakeExecutor(long_answer, delay=0.02)
    with make_client(executor) as client:
        app = client.app
        with client.websocket_connect("/device") as ws:
            ws.send_json(HELLO)
            ask(ws, 1)
            assert json.loads(receive(ws)["text"]) == {"type": "reply_start", "turn": 1}
            assert receive(ws).get("bytes")  # пошёл звук — рвём связь посреди ответа
        hub = app.state.hub  # type: ignore[attr-defined]
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


def test_two_speakers_louder_one_answers() -> None:
    # номера ходов колонок (5 и 9) не совпадают с номерами хаба (1, 2…): путаница номеров видна
    executor = FakeExecutor(["Сейчас полдень."])
    with (
        make_client(executor) as client,
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
