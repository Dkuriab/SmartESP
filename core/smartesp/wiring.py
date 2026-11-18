"""Сборка ядра (вместе с main.py — аналог SmartEsp.ino): части, разделы настроек, приложение.

Здесь видно, кто с кем соединён и в каком порядке ядро греется и останавливается.
Реестры реализаций и запуск процесса — в main.py.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from fastapi import FastAPI, WebSocket

from smartesp.api import create_api, mount_ui
from smartesp.config import Config, ConfigFile, ExecutorConfig, StageConfig, SttConfig
from smartesp.contracts import Analyzer, Executor, Section, SpeechToText, Stage, TextToSpeech
from smartesp.control import Core
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub, WebSocketConnection
from smartesp.events import EventBus
from smartesp.lifecycle import Answering, LiveAnswering, RunFile, guarded, timed
from smartesp.stages import run_stages
from smartesp.tts import VoiceManager

WARM_UP_PCM = bytes(16000)  # 0,5 с тишины (16 кГц, s16le)
WARM_UP_TIMEOUT_S = 120.0  # дольше прогрева исполнителя не ждём
DRAIN_S = 10.0  # звучащим ответам при остановке
UNLOAD_S = 1.0  # выгрузка модели из Ollama
TURN_WAIT_S = 120.0  # сколько старая модель ждёт конца идущих ходов перед выгрузкой

logger = logging.getLogger("smartesp")


class StartupError(Exception):
    """Ядро не может стартовать: понятное сообщение для человека."""


@dataclass(frozen=True)
class Kinds:
    """Реестры реализаций по полю kind из config.yaml."""

    stt: Mapping[str, Callable[[SttConfig], SpeechToText]]
    tts: Mapping[str, Callable[[Path, str], TextToSpeech]]  # (путь голоса, голос)
    executors: Mapping[str, Callable[[ExecutorConfig], Executor]]
    stages: Mapping[str, Callable[[StageConfig], Stage]]


@dataclass(frozen=True)
class Ollama:
    """Сведения Ollama для status и списка моделей."""

    models: Callable[[], Awaitable[list[tuple[str, int]]]]
    loaded: Callable[[], Awaitable[list[str]]]


def _pick[T](registry: Mapping[str, T], kind: str, what: str) -> T:
    """Реализация из реестра по имени; неизвестное имя — StartupError со списком известных."""
    if kind not in registry:
        known = ", ".join(sorted(registry)) or "нет"
        raise StartupError(f"Неизвестный {what} kind={kind!r}; известные: {known}")
    return registry[kind]


def check_kinds(config: Config, kinds: Kinds) -> None:
    """Проверяет виды stt, tts, входного исполнителя и обработчиков до старта сервера."""
    _pick(kinds.stt, config.stt.kind, "stt")
    _pick(kinds.tts, config.tts.kind, "tts")
    _pick(kinds.executors, config.entry_executor().kind, "executor")
    for stage in config.stages:
        _pick(kinds.stages, stage.kind, "stage")


def with_stage_hints(prompt: str, stages: Sequence[Stage]) -> str:
    """Системный промпт входного исполнителя + правила включённых обработчиков."""
    hints = [stage.prompt_hint for stage in stages if stage.prompt_hint]
    return "\n".join([prompt, *hints])


def make_answering(config: Config, kinds: Kinds) -> Answering:
    """Обработчики из настроек и входной исполнитель с их правилами в промпте."""
    stages = [(_pick(kinds.stages, s.kind, "stage")(s), s.timeout_ms / 1000) for s in config.stages]
    entry = config.entry_executor()
    prompt = with_stage_hints(entry.system_prompt, [stage for stage, _ in stages])
    entry = entry.model_copy(update={"system_prompt": prompt})
    executor = _pick(kinds.executors, entry.kind, "executor")(entry)
    return functools.partial(run_stages, stages), executor


async def _build_answering(kinds: Kinds, live: LiveAnswering, config: Config) -> Answering:
    return await live.build(make_answering(config, kinds), WARM_UP_TIMEOUT_S)


async def _device_names(config: Config) -> dict[str, str]:
    return {device_id: device.name for device_id, device in config.devices.items()}


async def _history_limits(config: Config) -> tuple[int, int]:
    return config.history.max_turns, config.history.max_age_s


def _sections(hub: DeviceHub, history: History, live: LiveAnswering, kinds: Kinds) -> dict[str, Section]:
    """Разделы, применяемые на лету (tts пульт открывает через менеджер голосов)."""
    answering = Section(functools.partial(_build_answering, kinds, live), live.use, live.release)
    return {
        "devices": Section(_device_names, lambda names: hub.set_names(cast(dict[str, str], names))),
        "history": Section(_history_limits, lambda new: history.set_limits(*cast(tuple[int, int], new))),
        "executors": answering,
        "stages": answering,  # правила обработчиков в промпте: пересобираем и исполнителя
    }


@dataclass
class Assembly:
    """Собранное ядро: части, пульт, приложение и фоновые задачи."""

    config: Config
    kinds: Kinds
    bus: EventBus
    hub: DeviceHub
    history: History
    orchestrator: Orchestrator
    live: LiveAnswering
    voices: VoiceManager
    voice_ready: asyncio.Event
    core: Core
    run_file: RunFile
    app: FastAPI = field(init=False)
    running: asyncio.Task[None] | None = None  # оркестратор
    warming: asyncio.Task[None] | None = None  # прогрев частей


def assemble(
    store: ConfigFile,
    config: Config,
    home: Path,
    kinds: Kinds,
    ollama: Ollama,
    *,
    version: str,
    token: str,
    ui_dir: Path,
) -> Assembly:
    """Создаёт части без моделей (их греет start) и приложение: /device, /api/v1, интерфейс."""
    bus = EventBus()
    arbitration = config.arbitration
    names = {device_id: device.name for device_id, device in config.devices.items()}
    hub = DeviceHub(arbitration.window_ms / 1000, arbitration.late_ms / 1000, names, events=bus)
    history = History(config.history.max_turns, config.history.max_age_s)
    orchestrator = Orchestrator(hub, None, None, None, None, history, events=bus)

    def install(analyze: Analyzer, executor: Executor) -> None:
        orchestrator.use_analyzer(analyze)
        orchestrator.use_executor(executor)

    live = LiveAnswering(install, orchestrator.wait_turns, turn_wait_s=TURN_WAIT_S, unload_s=UNLOAD_S)
    voice_ready = asyncio.Event()

    def on_voice(tts: TextToSpeech, kind: str, voice: str) -> None:
        orchestrator.use_tts(tts)
        voice_ready.set()

    voices = VoiceManager(home, kinds.tts, on_voice, events=bus)
    core = Core(
        store,
        _sections(hub, history, live, kinds),
        events=bus,
        feed=bus,
        voices=voices,
        models=ollama.models,
        loaded=ollama.loaded,
        devices=hub.devices,
        version=version,
    )
    run_file = RunFile(home / "run" / "core.json")
    parts = Assembly(
        config, kinds, bus, hub, history, orchestrator, live, voices, voice_ready, core, run_file
    )
    parts.app = _build_app(parts, token, ui_dir, version)
    return parts


def _build_app(parts: Assembly, token: str, ui_dir: Path, version: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        start(parts)  # до приёма соединений: голос открывается раньше любого PATCH
        try:
            yield
        finally:
            await finish(parts)

    app = FastAPI(title="SmartESP core", version=version, lifespan=lifespan)

    @app.websocket("/device")
    async def device(ws: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        await ws.accept()
        await parts.hub.handle(WebSocketConnection(ws))

    app.include_router(create_api(parts.core, parts.bus, token))
    mount_ui(app, ui_dir)  # последним: монтирование на / перехватывает всё, что объявлено позже
    return app


def start(parts: Assembly) -> None:
    """Запускает фон: оркестратор, открытие голоса (с повторами) и прогрев частей."""
    tts = parts.config.tts
    voice = asyncio.create_task(parts.voices.open(tts.kind, tts.voice, retry=True), name="voice-open")
    parts.running = asyncio.create_task(parts.orchestrator.run(), name="orchestrator")
    parts.warming = asyncio.create_task(warm_up(parts, voice), name="warm-up")
    parts.running.add_done_callback(_log_crash)
    parts.warming.add_done_callback(_log_crash)


async def warm_up(parts: Assembly, voice: asyncio.Task[bool]) -> None:
    """Прогрев в фоне: STT, обработчики и исполнитель (до 120 с), голос; затем ready.

    Сбой одного шага пишется в журнал и не мешает остальным.
    """
    await timed("STT", _warm_stt(parts))
    answering = guarded("исполнитель", lambda: make_answering(parts.config, parts.kinds))
    if answering is not None:
        await parts.live.warm_startup(answering, WARM_UP_TIMEOUT_S)
    waiting = asyncio.create_task(parts.voice_ready.wait())
    try:  # хватит любого голоса, хоть запасного: нужный может ещё качаться
        await asyncio.wait([voice, waiting], return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiting.cancel()
    if not parts.voice_ready.is_set():
        logger.error("Голоса нет: колонки будут получать сигнал ошибки")
    parts.core.set_state("ready")
    logger.info("Ядро готово")


async def _warm_stt(parts: Assembly) -> None:
    stt = parts.kinds.stt[parts.config.stt.kind](parts.config.stt)
    parts.orchestrator.use_stt(stt)
    await stt.transcribe(WARM_UP_PCM)


async def stop(parts: Assembly) -> None:
    """Честная остановка: договорить, отключить колонки, выгрузить модель, убрать файл запуска."""
    logger.info("Остановка: новые ходы и правки не принимаются")
    parts.core.set_state("stopping")
    parts.hub.stop_accepting()
    parts.orchestrator.stop_accepting()
    parts.live.close()  # освобождения старых моделей больше не ждут ходов: их выгрузит unload_all
    await _cancel(parts.warming)  # прогрев, если ещё идёт; оркестратор — в finish
    await parts.core.aclose()  # правка в работе отменяется: живой исполнитель больше не меняется
    await parts.orchestrator.drain(DRAIN_S)
    logger.info("Остановка: идущие ходы закончены")
    await parts.hub.close_all()
    logger.info("Остановка: колонки отключены")
    await parts.live.unload_all()
    await parts.voices.aclose()
    parts.run_file.remove()
    logger.info("Остановка: готово")


async def finish(parts: Assembly) -> None:
    """Снимает фоновые задачи и таймеры хаба (после остановки сервера)."""
    await _cancel(parts.running, parts.warming)
    await parts.voices.aclose()
    await parts.hub.aclose()


async def _cancel(*tasks: asyncio.Task[None] | None) -> None:
    started = [task for task in tasks if task is not None]
    for task in started:
        task.cancel()
    await asyncio.gather(*started, return_exceptions=True)


def _log_crash(task: asyncio.Task[None]) -> None:
    """Фоновая задача ядра упала — громко в журнал (оркестратор не должен завершаться сам)."""
    if not task.cancelled() and task.exception() is not None:
        logger.critical("Задача %s упала", task.get_name(), exc_info=task.exception())
