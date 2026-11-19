"""Сборка ядра (вместе с main.py — аналог SmartEsp.ino): части, разделы настроек, приложение.

Здесь видно, кто с кем соединён и в каком порядке ядро греется и останавливается.
Реестры реализаций и запуск процесса — в main.py.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket

from smartesp.api import create_api, mount_ui
from smartesp.config import Config, ConfigFile
from smartesp.contracts import Analyzer, Executor, TextToSpeech
from smartesp.control import Core
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub, WebSocketConnection
from smartesp.events import EventBus
from smartesp.kinds import (
    Kinds,
    build_answering,
    kinds_validator,
    member_specs,
    prompt_stages,
)
from smartesp.lifecycle import (
    Answering,
    CapabilityCache,
    CapabilityRetry,
    LiveAnswering,
    RunFile,
    guarded,
    timed,
)
from smartesp.network import NetworkPrompts
from smartesp.notify import Announcer
from smartesp.sections import live_sections, speech_settings
from smartesp.tts import VoiceManager

WARM_UP_PCM = bytes(16000)  # 0,5 с тишины (16 кГц, s16le)
WARM_UP_TIMEOUT_S = 120.0  # дольше прогрева исполнителя не ждём
DRAIN_S = 10.0  # звучащим ответам при остановке
UNLOAD_S = 1.0  # выгрузка модели из Ollama
TURN_WAIT_S = 150.0  # сколько старые модели ждут конца идущих ходов перед выгрузкой (передача — до 90 с)

logger = logging.getLogger("smartesp")


@dataclass(frozen=True)
class Ollama:
    """Сведения Ollama для status, списка моделей и проверки умения инструментов."""

    models: Callable[[], Awaitable[list[tuple[str, int]]]]
    loaded: Callable[[], Awaitable[list[str]]]
    capabilities: Callable[[str], Awaitable[frozenset[str]]]


async def _build_answering(
    kinds: Kinds, live: LiveAnswering, capabilities: CapabilityCache, config: Config
) -> Answering:
    return await live.build(await build_answering(config, kinds, capabilities.get), WARM_UP_TIMEOUT_S)


@dataclass
class Assembly:
    """Собранное ядро: части, пульт, приложение и фоновые задачи."""

    config: Config
    kinds: Kinds
    bus: EventBus
    hub: DeviceHub
    history: History
    orchestrator: Orchestrator
    announcer: Announcer  # речь по инициативе: очередь объявлений
    live: LiveAnswering
    capabilities: CapabilityCache  # возможности моделей: умеют ли инструменты
    retry: CapabilityRetry  # пересборка сети, когда станут известны возможности моделей
    voices: VoiceManager
    voice_ready: asyncio.Event
    core: Core
    run_file: RunFile
    app: FastAPI = field(init=False)
    running: asyncio.Task[None] | None = None  # оркестратор
    warming: asyncio.Task[None] | None = None  # прогрев частей
    retrying: asyncio.Task[None] | None = None  # повтор запроса возможностей моделей


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
    announcer = Announcer(hub, orchestrator.speech, events=bus)
    orchestrator.use_announcer(announcer)
    use_speech = speech_settings(orchestrator, announcer)
    use_speech(config.speech)

    def install(analyze: Analyzer, executor: Executor) -> None:
        orchestrator.use_analyzer(analyze)
        orchestrator.use_executor(executor)

    live = LiveAnswering(
        install,
        orchestrator.wait_turns,
        turn_wait_s=TURN_WAIT_S,
        unload_s=UNLOAD_S,
        member_warm_s=WARM_UP_TIMEOUT_S,
    )
    capabilities = CapabilityCache(ollama.capabilities)
    retry = CapabilityRetry(  # Ollama поднялась позже ядра — пересборка, как правка executors
        live,
        capabilities.probe,
        lambda: _build_answering(kinds, live, capabilities, store.config),
    )
    prompts = NetworkPrompts(  # настройки = живые части
        lambda: store.config.entry_executor().id,
        lambda: member_specs(store.config),
        lambda: prompt_stages(store.config, kinds),
        capabilities.known,
        lambda: live.executor,
    )
    voice_ready = asyncio.Event()

    def on_voice(tts: TextToSpeech, kind: str, voice: str) -> None:
        orchestrator.use_tts(tts)
        voice_ready.set()

    voices = VoiceManager(home, kinds.tts, on_voice, events=bus)
    core = Core(
        store,
        live_sections(
            hub, history, live, lambda config: _build_answering(kinds, live, capabilities, config), use_speech
        ),
        events=bus,
        feed=bus,
        voices=voices,
        models=ollama.models,
        loaded=ollama.loaded,
        devices=hub.devices,
        version=version,
        validate=kinds_validator(kinds),  # иначе после перезапуска ядро не стартует
        dispatcher_prompt=prompts.entry,
        executor_prompts=prompts.all,
        supports_tools=capabilities.supports_tools,
        executor_states=lambda: live.members_warmth,
    )
    run_file = RunFile(home / "run" / "core.json")
    parts = Assembly(
        config,
        kinds,
        bus,
        hub,
        history,
        orchestrator,
        announcer,
        live,
        capabilities,
        retry,
        voices,
        voice_ready,
        core,
        run_file,
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

    app.include_router(create_api(parts.core, parts.bus, token, port=parts.config.server.port))
    mount_ui(app, ui_dir)  # последним: монтирование на / перехватывает всё, что объявлено позже
    return app


def start(parts: Assembly) -> None:
    """Запускает фон: оркестратор, открытие голоса (с повторами), прогрев частей и повтор возможностей."""
    tts = parts.config.tts
    voice = asyncio.create_task(parts.voices.open(tts.kind, tts.voice, retry=True), name="voice-open")
    parts.running = asyncio.create_task(parts.orchestrator.run(), name="orchestrator")
    parts.warming = asyncio.create_task(warm_up(parts, voice), name="warm-up")
    parts.retrying = asyncio.create_task(parts.retry.run(), name="capabilities-retry")
    for task in (parts.running, parts.warming, parts.retrying):
        task.add_done_callback(_log_crash)


async def warm_up(parts: Assembly, voice: asyncio.Task[bool]) -> None:
    """Прогрев в фоне: STT, обработчики и входной исполнитель сети (до 120 с), голос; затем ready.

    Остальные исполнители сети греются в фоне после подмены и ready не задерживают.
    Сбой одного шага пишется в журнал и не мешает остальным.
    """
    await timed("STT", _warm_stt(parts))
    answering = await guarded(
        "исполнитель", build_answering(parts.config, parts.kinds, parts.capabilities.get)
    )
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
    """Честная остановка: договорить, бросить очередь речи, отключить колонки, выгрузить модель,
    убрать файл запуска."""
    logger.info("Остановка: новые ходы и правки не принимаются")
    parts.core.set_state("stopping")
    parts.hub.stop_accepting()
    parts.orchestrator.stop_accepting()
    parts.live.close()  # освобождения старых моделей больше не ждут ходов: их выгрузит unload_all
    await _cancel(parts.warming, parts.retrying)  # прогрев и повтор, если идут; оркестратор — в finish
    await parts.core.aclose()  # правка в работе отменяется: живой исполнитель больше не меняется
    await parts.orchestrator.drain(DRAIN_S)
    logger.info("Остановка: идущие ходы закончены")
    await parts.announcer.aclose()  # очередь речи бросается до отключения колонок
    await parts.hub.close_all()
    logger.info("Остановка: колонки отключены")
    await parts.live.unload_all()
    await parts.voices.aclose()
    parts.run_file.remove()
    logger.info("Остановка: готово")


async def finish(parts: Assembly) -> None:
    """Снимает фоновые задачи и таймеры хаба (после остановки сервера)."""
    await _cancel(parts.running, parts.warming, parts.retrying)
    await parts.announcer.aclose()
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
