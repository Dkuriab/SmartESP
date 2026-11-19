"""Помощники тестов связки: ядро целиком на подделках, без моделей, сети и Ollama."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx

from fakes.fake_connection import FakeConnection
from fakes.fake_executor import FakeOllama
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.config import ConfigFile, ExecutorConfig
from smartesp.contracts import Executor, TextToSpeech
from smartesp.kinds import Kinds
from smartesp.main import STAGE_KINDS
from smartesp.wiring import Assembly, Ollama, assemble

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FAST_ARBITRATION = "arbitration:\n  window_ms: 20\n  late_ms: 200\n"
FRAME = bytes(1024)


async def no_models() -> list[tuple[str, int]]:
    return []


async def no_loaded() -> list[str]:
    return []


async def no_capabilities(model: str) -> frozenset[str]:
    return frozenset()


async def with_tools(model: str) -> frozenset[str]:
    return frozenset({"completion", "tools"})


NO_OLLAMA = Ollama(no_models, no_loaded, no_capabilities)
TOOLS_OLLAMA = Ollama(no_models, no_loaded, with_tools)  # все модели умеют инструменты


def put_voice(home: Path) -> None:
    """Кладёт «скачанный» голос silero (по умолчанию в настройках): файла достаточно."""
    path = home / "voices" / "silero" / "v5_ru.pt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def fake_kinds(
    executor: Callable[[ExecutorConfig], Executor],
    *,
    text: str = "сколько времени",
    tts: TextToSpeech | None = None,
) -> Kinds:
    """Реестры с подделками под умолчания config.yaml (mlx_whisper, silero, ollama)."""
    voice = tts or FakeTTS(bytes_per_char=32)
    return Kinds(
        stt={"mlx_whisper": lambda c: FakeSTT(text)},
        tts={"silero": lambda path, name: voice},
        executors={"ollama": executor},
        stages=STAGE_KINDS,
    )


def make_core(
    home: Path, kinds: Kinds, config_yaml: str = FAST_ARBITRATION, ollama: Ollama = NO_OLLAMA
) -> Assembly:
    """Ядро на подделках в папке home: config.yaml, голос, сборка как в main."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(config_yaml, encoding="utf-8")
    put_voice(home)
    store = ConfigFile(home / "config.yaml")
    config = store.load()
    return assemble(store, config, home, kinds, ollama, version="test", token=TOKEN, ui_dir=home / "no-ui")


def ollama_factory(
    made: list[FakeOllama],
    parts: list[str] | None = None,
    *,
    delay: float = 0,
    warm_gate: asyncio.Event | None = None,
) -> Callable[[ExecutorConfig], Executor]:
    """Фабрика исполнителей: на каждый вызов — новый FakeOllama с моделью и промптом из настроек."""

    def make(config: ExecutorConfig) -> Executor:
        answer = parts or ["Сейчас полдень."]
        executor = FakeOllama(
            answer, config.model, delay=delay, warm_gate=warm_gate, prompt=config.system_prompt
        )
        made.append(executor)
        return executor

    return make


def client(core: Assembly) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url="http://t")


async def eventually(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def connect(core: Assembly, device_id: str) -> tuple[FakeConnection, asyncio.Task[None]]:
    """Подключает поддельную колонку к хабу ядра и ждёт, пока он её увидит."""
    conn = FakeConnection()
    task = asyncio.create_task(core.hub.handle(conn))
    conn.feed_json("hello", fw="2.0", device_id=device_id, protocol=2)
    await eventually(lambda: any(d.device_id == device_id and d.connected for d in core.hub.devices()))
    return conn, task


def ask(conn: FakeConnection, turn: int) -> None:
    """Колонка: wake, немного звука и конец реплики."""
    conn.feed_json("wake", turn=turn, level=-30.0)
    for _ in range(5):
        conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=turn, reason="vad")


def sent_types(conn: FakeConnection) -> list[str]:
    return [m["type"] for m in conn.sent_json()]
