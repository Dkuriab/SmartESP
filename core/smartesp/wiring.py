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

from smartesp.api import BodyLimit, create_api, mount_ui
from smartesp.config import Config, ConfigFile
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
    file_player,
    live_answering,
    voice_manager,
)
from smartesp.tools import McpHub

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
    kinds: Kinds, live: LiveAnswering, capabilities: CapabilityCache, tools: McpHub, config: Config
) -> Answering:
    part = await _answering(config, kinds, capabilities, tools)
    return await live.build(part, WARM_UP_TIMEOUT_S)


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
    hub, history, orchestrator, announcer, use_speech = conversation(config, bus)
    live = live_answering(orchestrator, turn_wait_s=TURN_WAIT_S, unload_s=UNLOAD_S, warm_s=WARM_UP_TIMEOUT_S)
    capabilities = CapabilityCache(ollama.capabilities)
    tools = McpHub(
        home,
        on_announce=lambda text, person, connector: announcer.say(NO_DEVICE, text, connector),
        on_tools=lambda: parts.refresh.changed(),
    )
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
        voices,
        voice_ready,
        run_file,
    )
    build = functools.partial(_build_answering, kinds, live, capabilities, tools)  # (настройки) → пара
    # Ollama поднялась позже ядра — пересборка, как правка executors
    parts.retry = CapabilityRetry(live, capabilities.probe, lambda: build(store.config))
    parts.core = control(parts, store, ollama, version, build, use_speech)
    # инструменты сменились — пересборка в очереди правок: не гоняется с ними
    parts.refresh = ToolsRefresh(
        lambda: live.executor is not None, lambda: parts.core.rebuild(ANSWERING_SECTIONS)
    )
    parts.files = file_player(hub, bus)
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

    api = create_api(parts.core, parts.bus, token, port=parts.config.server.port, files=parts.files)
    app.include_router(api)
    app.add_middleware(BodyLimit, token=token)  # предел тела и токен ходов через API — до чтения тела
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
    parts.run_file.remove()
    logger.info("Остановка: готово")


async def finish(parts: Assembly) -> None:
    """Снимает фоновые задачи и таймеры хаба (после остановки сервера)."""
    await cancel_tasks(parts.running, parts.warming, parts.retrying, parts.refreshing)
    await parts.tools.aclose()
    await parts.announcer.aclose()
    await parts.files.aclose()
    await parts.voices.aclose()
    await parts.hub.aclose()
