"""Сборка ядра (вместе с main.py — аналог SmartEsp.ino): части, разделы настроек, приложение.

Здесь видно, кто с кем соединён и в каком порядке ядро греется и останавливается.
Реестры реализаций и запуск процесса — в main.py.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket

from smartesp.api import BodyLimit, LogBuffer, add_device_files, add_device_streams, create_api, mount_ui
from smartesp.config import Config, ConfigFile
from smartesp.config.connectors import REPO_DIR
from smartesp.contracts import Analyzer
from smartesp.conversation import tool_observer
from smartesp.devices import WebSocketConnection
from smartesp.events import EventBus
from smartesp.kinds import Kinds, Ollama, build_answering, connector_specs
from smartesp.lifecycle import (
    Answering,
    CapabilityCache,
    CapabilityRetry,
    LiveAnswering,
    RunFile,
    ToolsRefresh,
    cancel_tasks,
    guarded,
    log_crash,
    timed,
)
from smartesp.network import ExecutorNetwork
from smartesp.parts import (
    ANSWERING_SECTIONS,
    Assembly,
    control,
    conversation,
    live_answering,
    voice_manager,
)
from smartesp.stages import SYSTEM_FACTS, SystemSnapshot
from smartesp.streams import Streams, capture_probe, ffmpeg_decoder
from smartesp.stt import find_ffmpeg
from smartesp.tasks import TaskRegistry
from smartesp.tools import McpHub
from smartesp.training import Training
from smartesp.updates import Updates

__all__ = ["Assembly", "Ollama", "assemble", "finish", "start", "stop"]

WARM_UP_PCM = bytes(16000)  # 0,5 с тишины (16 кГц, s16le)
WARM_UP_TIMEOUT_S = 120.0  # дольше прогрева исполнителя не ждём
DRAIN_S = 10.0  # звучащим ответам при остановке
UNLOAD_S = 1.0  # выгрузка модели из Ollama
TURN_WAIT_S = 150.0  # сколько старые модели ждут конца идущих ходов перед выгрузкой (передача — до 90 с)
NO_DEVICE = ""  # колонки нет: объявление коннектора — на последней активной или первой подключённой
TOOLS_CLOSE_S = 2.0  # коннекторам на закрытие при остановке (затем SIGKILL, ещё ≤1 с)

logger = logging.getLogger("smartesp")


async def _answering(
    config: Config, kinds: Kinds, capabilities: CapabilityCache, tools: McpHub
) -> tuple[Analyzer, ExecutorNetwork]:
    """Обработчики и сеть из настроек; вызовы инструментов сети — в живую подсветку хода."""
    observe = tool_observer(tools.connector_of)
    return await build_answering(config, kinds, capabilities.get, tools, observe)


async def _build_answering(
    kinds: Kinds,
    live: LiveAnswering,
    capabilities: CapabilityCache,
    tools: McpHub,
    config: Config,
    *,
    warm: bool = True,
) -> Answering:
    part = await _answering(config, kinds, capabilities, tools)
    return await live.build(part, WARM_UP_TIMEOUT_S, warm=warm)


def _system_snapshot(tasks: TaskRegistry, tools: McpHub) -> SystemSnapshot:
    """Снимок для обработчика «система»: идущие задачи и готовые коннекторы."""
    running = [(t.title, t.eta) for t in tasks.tasks() if t.status == "running"]
    return SystemSnapshot(running, [c.name for c in tools.states() if c.state == "ready" and c.kind == "mcp"])


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
    logs: LogBuffer,
) -> Assembly:
    """Создаёт части без моделей (их греет start) и приложение: /device, /api/v1, интерфейс.

    logs — журнал процесса для WebSocket /api/v1/logs.
    """
    bus = EventBus()
    hub, history, orchestrator, announcer, files, use_speech = conversation(config, bus)
    live = live_answering(orchestrator, turn_wait_s=TURN_WAIT_S, unload_s=UNLOAD_S, warm_s=WARM_UP_TIMEOUT_S)
    capabilities = CapabilityCache(ollama.capabilities)
    tasks = TaskRegistry(bus, hub.device_name)  # «В работе»: запоздавшие ответы и задачи коннекторов
    orchestrator.use_tasks(tasks)
    tools = McpHub(
        home,
        on_announce=lambda text, person, connector: announcer.say(NO_DEVICE, text, connector),
        tasks=tasks,
        on_tools=lambda: parts.refresh.changed(),
        # клиенты ядра (бот) ходят в его API: адрес и токен — им в окружение
        client_env={"SMARTESP_URL": f"http://127.0.0.1:{config.server.port}", "SMARTESP_TOKEN": token},
    )
    SYSTEM_FACTS.use(functools.partial(_system_snapshot, tasks, tools))  # обработчик «система»
    voices, voice_ready = voice_manager(home, kinds, orchestrator, bus)
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
        tools,
        tasks,
        voices,
        voice_ready,
        run_file,
    )
    build = functools.partial(_build_answering, kinds, live, capabilities, tools)  # (настройки) → пара
    # Ollama поднялась позже ядра — пересборка, как правка executors
    parts.retry = CapabilityRetry(live, capabilities.probe, lambda: build(store.config))
    parts.core = control(parts, home, store, ollama, version, build, use_speech)
    # инструменты сменились — пересборка в очереди правок: не гоняется с ними
    parts.refresh = ToolsRefresh(
        lambda: live.executor is not None, lambda: parts.core.rebuild(ANSWERING_SECTIONS)
    )
    parts.files = files
    parts.updates = Updates(home / "run" / "updates", hub.send_update)  # колонка качает файл сама
    # поток звука (музыка коннектора): колонка тянет его сама, отчёты — потокам
    decode, probe = ffmpeg_decoder(find_ffmpeg), capture_probe(find_ffmpeg)  # probe — звук Mac (BlackHole)
    parts.streams = Streams(hub, hub.devices, hub.last_active_device, decode, events=bus, probe=probe)
    hub.use_stream_listener(parts.streams.report)
    parts.training = Training(  # наборы — в репозитории, данные — в папке данных
        REPO_DIR / "trainers",
        home / "training",
        hub.record,
        lambda device_id: hub.supports_proactive(device_id) and not hub.is_busy(device_id),
        parts.updates.install,  # модель прогона — на колонку по воздуху
    )
    parts.app = _build_app(parts, token, ui_dir, version, logs)
    return parts


def _build_app(parts: Assembly, token: str, ui_dir: Path, version: str, logs: LogBuffer) -> FastAPI:
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

    port = parts.config.server.port
    api = create_api(
        parts.core,
        parts.bus,
        token,
        port=port,
        files=parts.files,
        logs=logs,
        tasks=parts.tasks,
        training=parts.training,
        updates=parts.updates,
        streams=parts.streams,
    )
    app.include_router(api)
    app.add_middleware(BodyLimit, token=token)  # предел тела и токен ходов через API — до чтения тела
    add_device_files(app, parts.updates)  # файлы обновлений для колонок (без токена API)
    add_device_streams(app, parts.streams)  # звук потоков для колонок (без токена API)
    mount_ui(app, ui_dir)  # последним: монтирование на / перехватывает всё, что объявлено позже
    return app


def start(parts: Assembly) -> None:
    """Запускает фон: оркестратор, открытие голоса (с повторами), прогрев частей, повтор возможностей
    и коннекторы (готовность голоса их не ждёт: сеть пересоберётся, когда они встанут)."""
    tts = parts.config.tts
    voice = asyncio.create_task(parts.voices.open(tts.kind, tts.voice, retry=True), name="voice-open")
    parts.running = asyncio.create_task(parts.orchestrator.run(), name="orchestrator")
    parts.warming = asyncio.create_task(warm_up(parts, voice), name="warm-up")
    parts.retrying = asyncio.create_task(parts.retry.run(), name="capabilities-retry")
    parts.refreshing = asyncio.create_task(parts.refresh.run(), name="tools-refresh")
    parts.tools.apply_soon(connector_specs(parts.config))
    for task in (parts.running, parts.warming, parts.retrying, parts.refreshing):
        task.add_done_callback(log_crash)


async def warm_up(parts: Assembly, voice: asyncio.Task[bool]) -> None:
    """Прогрев в фоне: STT, обработчики и входной исполнитель сети (до 120 с), голос; затем ready.

    Остальные исполнители сети греются в фоне после подмены и ready не задерживают.
    Сбой одного шага пишется в журнал и не мешает остальным.
    """
    await timed("STT", _warm_stt(parts))
    answering = await guarded(
        "исполнитель", _answering(parts.config, parts.kinds, parts.capabilities, parts.tools)
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
    """Честная остановка: остановить файлы на колонках, договорить (одновременно закрыть коннекторы),
    бросить очередь речи, отключить колонки, выгрузить модель, убрать файл запуска."""
    logger.info("Остановка: новые ходы и правки не принимаются")
    parts.core.set_state("stopping")
    parts.hub.stop_accepting()
    parts.orchestrator.stop_accepting()
    parts.live.close()  # освобождения старых моделей больше не ждут ходов: их выгрузит unload_all
    await parts.files.aclose()  # файл на колонке может играть минуты — не ждём его
    await parts.streams.aclose()  # музыка на колонках останавливается
    await cancel_tasks(parts.warming, parts.retrying, parts.refreshing)  # оркестратор — в finish
    # коннекторы закрываются, пока договариваются ходы (их вызовы инструментов уже не пройдут)
    closing = asyncio.create_task(parts.tools.aclose(TOOLS_CLOSE_S), name="tools-close")
    await parts.core.aclose()  # правка в работе отменяется: живой исполнитель больше не меняется
    await parts.orchestrator.drain(DRAIN_S)
    logger.info("Остановка: идущие ходы закончены")
    await closing
    logger.info("Остановка: коннекторы остановлены")
    await parts.announcer.aclose()  # очередь речи бросается до отключения колонок
    await parts.hub.close_all()
    logger.info("Остановка: колонки отключены")
    await parts.live.unload_all()
    await parts.voices.aclose()
    await parts.training.aclose()  # шаг обучения (подпроцесс) не переживает ядро
    parts.run_file.remove()
    logger.info("Остановка: готово")


async def finish(parts: Assembly) -> None:
    """Снимает фоновые задачи и таймеры хаба (после остановки сервера)."""
    await cancel_tasks(parts.running, parts.warming, parts.retrying, parts.refreshing)
    await parts.tools.aclose()
    await parts.announcer.aclose()
    await parts.files.aclose()
    await parts.streams.aclose()
    await parts.voices.aclose()
    await parts.training.aclose()
    await parts.hub.aclose()
