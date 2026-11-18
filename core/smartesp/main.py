"""Связка ядра (аналог SmartEsp.ino): создаёт модули по config.yaml и соединяет их.

Своей логики здесь нет: реестры реализаций, сборка приложения, прогрев и запуск.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol, runtime_checkable

import uvicorn
from fastapi import FastAPI, WebSocket

from smartesp.config import (
    Config,
    ExecutorConfig,
    StageConfig,
    SttConfig,
    TtsConfig,
    data_dir,
    load_config,
)
from smartesp.contracts import Executor, ExecutorError, SpeechToText, Stage, TextToSpeech
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub, WebSocketConnection
from smartesp.executors import OllamaExecutor
from smartesp.stages import run_stages
from smartesp.stt import MlxWhisperSTT
from smartesp.tts import PiperTTS

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 5
WARM_UP_PCM = bytes(16000)  # 0,5 с тишины (16 кГц, s16le)
WARM_UP_TIMEOUT_S = 120.0  # дольше прогрева исполнителя не ждём: старт не должен висеть

logger = logging.getLogger("smartesp")


class StartupError(Exception):
    """Ядро не может стартовать: понятное сообщение для человека."""


def _piper(config: TtsConfig, home: Path) -> TextToSpeech:
    """Голос Piper из <data_dir>/voices/<voice>.onnx."""
    path = home / "voices" / f"{config.voice}.onnx"
    if not path.exists():
        raise StartupError(f"Нет голоса Piper: {path}. Скачайте его: tools/download_voice.sh {config.voice}")
    return PiperTTS(path)


STT_KINDS: dict[str, Callable[[SttConfig], SpeechToText]] = {
    "mlx_whisper": lambda c: MlxWhisperSTT(c.model, c.language),
}
TTS_KINDS: dict[str, Callable[[TtsConfig, Path], TextToSpeech]] = {
    "piper": _piper,
}
EXECUTOR_KINDS: dict[str, Callable[[ExecutorConfig], Executor]] = {
    "ollama": lambda c: OllamaExecutor(c.model, c.system_prompt, c.keep_alive),
}
STAGE_KINDS: dict[str, Callable[[StageConfig], Stage]] = {}  # обработчики появятся на этапе 2


@runtime_checkable
class _WarmsUp(Protocol):
    """Реализация, которую можно прогреть заранее (например, загрузить модель)."""

    async def warm_up(self) -> None: ...


def _pick[T](registry: dict[str, T], kind: str, what: str) -> T:
    """Реализация из реестра по имени; неизвестное имя — StartupError со списком известных."""
    if kind not in registry:
        known = ", ".join(sorted(registry)) or "нет"
        raise StartupError(f"Неизвестный {what} kind={kind!r}; известные: {known}")
    return registry[kind]


def build_app(
    config: Config,
    stt: SpeechToText,
    tts: TextToSpeech,
    executor: Executor,
    stages: list[tuple[Stage, float]],
) -> FastAPI:
    """Собирает приложение: хаб колонок, оркестратор и WebSocket /device.

    stages — пары (обработчик, таймаут в секундах). Хаб доступен как app.state.hub.
    """
    arbitration = config.arbitration
    names = {dev_id: d.name for dev_id, d in config.devices.items()}
    hub = DeviceHub(arbitration.window_ms / 1000, arbitration.late_ms / 1000, names)
    history = History(config.history.max_turns, config.history.max_age_s)
    analyze = functools.partial(run_stages, stages)
    orchestrator = Orchestrator(hub, stt, analyze, executor, tts, history)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(orchestrator.run(), name="orchestrator")
        task.add_done_callback(_log_crash)
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await hub.aclose()

    app = FastAPI(lifespan=lifespan)
    app.state.hub = hub

    @app.websocket("/device")
    async def device(ws: WebSocket) -> None:
        await ws.accept()
        await hub.handle(WebSocketConnection(ws))

    return app


def _log_crash(task: asyncio.Task[None]) -> None:
    """Оркестратор не должен завершаться сам: если упал — громко в журнал."""
    if not task.cancelled() and task.exception() is not None:
        logger.critical("Оркестратор остановился с ошибкой", exc_info=task.exception())


def _setup_logging(logs: Path) -> None:
    """Журнал в консоль и в logs/core.log (5 файлов по 1 МБ)."""
    logs.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)
    console = logging.StreamHandler()
    file = RotatingFileHandler(
        logs / "core.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (console, file):
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _create(
    config: Config, home: Path
) -> tuple[SpeechToText, TextToSpeech, Executor, list[tuple[Stage, float]]]:
    """Создаёт реализации, выбранные в настройках, через реестры."""
    stt = _pick(STT_KINDS, config.stt.kind, "stt")(config.stt)
    tts = _pick(TTS_KINDS, config.tts.kind, "tts")(config.tts, home)
    entry = config.entry_executor()
    executor = _pick(EXECUTOR_KINDS, entry.kind, "executor")(entry)
    stages = [(_pick(STAGE_KINDS, s.kind, "stage")(s), s.timeout_ms / 1000) for s in config.stages]
    return stt, tts, executor, stages


async def _warm_up(
    stt: SpeechToText, executor: Executor, executor_timeout_s: float = WARM_UP_TIMEOUT_S
) -> None:
    """Загружает модели заранее, чтобы первый вопрос не ждал. Сбой — предупреждение, не остановка.

    Прогрев исполнителя ограничен executor_timeout_s секундами.
    """
    if isinstance(executor, _WarmsUp):
        started = time.monotonic()
        try:
            async with asyncio.timeout(executor_timeout_s):
                await executor.warm_up()
            logger.info("Исполнитель прогрет за %.1f с", time.monotonic() - started)
        except ExecutorError as error:
            logger.warning("Ollama недоступна: %s. Ходы будут заканчиваться сигналом ошибки.", error)
        except TimeoutError:
            logger.warning("Исполнитель не прогрелся за %g с; запускаюсь без прогрева.", executor_timeout_s)
    started = time.monotonic()
    try:
        await stt.transcribe(WARM_UP_PCM)
        logger.info("STT прогрет за %.1f с", time.monotonic() - started)
    except Exception:
        logger.error("STT не прогрелся: распознавание, скорее всего, не работает", exc_info=True)


async def _serve(
    config: Config,
    stt: SpeechToText,
    tts: TextToSpeech,
    executor: Executor,
    stages: list[tuple[Stage, float]],
) -> None:
    """Прогрев и запуск uvicorn до Ctrl+C."""
    await _warm_up(stt, executor)
    app = build_app(config, stt, tts, executor, stages)
    host, port = config.server.host, config.server.port
    # log_config=None: uvicorn пишет через корневой журнал (консоль + core.log)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info", log_config=None))
    logger.info("Ядро слушает ws://%s:%d/device", host, port)
    await server.serve()


def main() -> None:
    """Точка входа: config.yaml → реестры → прогрев → сервер на server.host:server.port."""
    home = data_dir()
    _setup_logging(home / "logs")
    config_path = home / "config.yaml"
    try:
        config = load_config(config_path)
        logger.info("Настройки: %s", config_path)
        stt, tts, executor, stages = _create(config, home)
    except (StartupError, ValueError) as error:
        logger.error("Ядро не запущено: %s", error)
        raise SystemExit(f"Ядро не запущено: {error}") from error
    try:
        asyncio.run(_serve(config, stt, tts, executor, stages))
    except KeyboardInterrupt:
        logger.info("Ядро остановлено")
