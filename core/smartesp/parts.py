"""Связка: группы частей ядра для wiring.assemble — разговор, живой исполнитель, голос, пульт.

Логики здесь нет, только создание частей и их соединение (как в wiring.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI

from smartesp.config import Config, ConfigFile, SpeechConfig
from smartesp.contracts import Analyzer, Executor, Registrar, ServiceRecord, TextToSpeech
from smartesp.control import Core
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub
from smartesp.discovery import Advertiser, load_or_create_core_id, local_ipv4
from smartesp.events import EventBus
from smartesp.executors import CloudCatalog, fetch_lmstudio_models
from smartesp.fileplay import FilePlayer
from smartesp.kinds import Kinds, Ollama, kinds_validator, member_specs, prompt_stages
from smartesp.lifecycle import (
    CapabilityCache,
    CapabilityRetry,
    LiveAnswering,
    RunFile,
    ToolsRefresh,
)
from smartesp.network import NetworkPrompts
from smartesp.notify import Announcer
from smartesp.people import OnnxVoicePrint, People, download_model, model_path
from smartesp.sections import BuildAnswering, live_sections, speech_settings
from smartesp.sounds import Sounds
from smartesp.stages import SystemSnapshot
from smartesp.streams import Streams
from smartesp.stt import decode_audio, decode_file
from smartesp.tasks import TaskRegistry
from smartesp.tools import McpHub
from smartesp.training import Training
from smartesp.tts import VoiceManager
from smartesp.updates import Updates

ANSWERING_SECTIONS = ("executors",)  # раздел живого исполнителя (stages — тот же Section)


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
    tools: McpHub  # MCP-коннекторы: инструменты сети и объявления
    tasks: TaskRegistry  # «В работе»: отложенные задачи ядра и коннекторов
    voices: VoiceManager
    voice_ready: asyncio.Event
    run_file: RunFile
    retry: CapabilityRetry = field(init=False)  # пересборка сети, когда станут известны возможности моделей
    refresh: ToolsRefresh = field(init=False)  # пересборка сети, когда меняется список инструментов
    core: Core = field(init=False)
    files: FilePlayer = field(init=False)  # звуковые файлы на колонках
    training: Training = field(init=False)  # обучение моделей: наборы, цели, записи с колонок
    updates: Updates = field(init=False)  # обновления колонок по воздуху: прошивка и модель слова
    sounds: Sounds = field(init=False)  # свои звуки сигналов колонок: библиотека и доставка
    people: People = field(init=False)  # люди дома и узнавание голоса
    streams: Streams = field(init=False)  # потоки звука на колонках (музыка коннектора)
    discovery: Advertiser = field(init=False)  # объявление ядра в сети: колонки находят его сами
    app: FastAPI = field(init=False)
    running: asyncio.Task[None] | None = None  # оркестратор
    warming: asyncio.Task[None] | None = None  # прогрев частей
    retrying: asyncio.Task[None] | None = None  # повтор запроса возможностей моделей
    refreshing: asyncio.Task[None] | None = None  # пересборка сети под инструменты коннекторов


def conversation(
    config: Config, bus: EventBus
) -> tuple[DeviceHub, History, Orchestrator, Announcer, FilePlayer, Callable[[SpeechConfig], None]]:
    """Колонки, история, оркестратор, очередь объявлений и файлы на колонках; последнее — применение
    раздела speech. Объявление вытесняет файл: перед ним файл на колонке останавливается."""
    arbitration = config.arbitration
    names = {device_id: device.name for device_id, device in config.devices.items() if device.name}
    hub = DeviceHub(arbitration.window_ms / 1000, arbitration.late_ms / 1000, names, events=bus)
    hub.set_volumes({device_id: device.volume for device_id, device in config.devices.items()})
    history = History(config.history.max_turns, config.history.max_age_s)
    orchestrator = Orchestrator(hub, None, None, None, None, history, events=bus)
    files = FilePlayer(hub, hub.devices, decode_file, events=bus)  # разбор ffmpeg по ходу, итог — в ленту
    # результат отложенной задачи мягко прерывает звучащий ответ (договаривает предложение)
    announcer = Announcer(
        hub, orchestrator.speech, events=bus, preempt=files.preempt, interrupt=orchestrator.interrupt
    )
    orchestrator.use_announcer(announcer)
    use_speech = speech_settings(orchestrator, announcer)
    use_speech(config.speech)
    return hub, history, orchestrator, announcer, files, use_speech


def discovery(home: Path, port: int, version: str, registrar: Callable[[], Registrar]) -> Advertiser:
    """Объявление `_smartesp._tcp` на порту ядра; id ядра — в <home>/core_id (создаётся при публикации,
    не при сборке: схема API папку данных не трогает)."""
    return Advertiser(
        registrar, lambda ips: ServiceRecord(load_or_create_core_id(home), port, version, ips), local_ipv4
    )


def people_registry(home: Path, hub: DeviceHub) -> People:
    """Люди: реестр в <home>/people, модель отпечатков в <home>/models/speaker (качается по просьбе),
    образцы — с колонки тем же способом, что записи «Обучения»."""
    model = model_path(home)
    return People(
        home / "people",
        model,
        OnnxVoicePrint(model),
        lambda progress: download_model(home, progress=progress),
        hub.record,
        lambda device_id: hub.supports_proactive(device_id) and not hub.is_busy(device_id),
    )


def live_answering(
    orchestrator: Orchestrator, *, turn_wait_s: float, unload_s: float, warm_s: float
) -> LiveAnswering:
    """Живые обработчики и исполнитель: подмена ставит их в оркестратор."""

    def install(analyze: Analyzer, executor: Executor) -> None:
        orchestrator.use_analyzer(analyze)
        orchestrator.use_executor(executor)

    return LiveAnswering(
        install, orchestrator.wait_turns, turn_wait_s=turn_wait_s, unload_s=unload_s, member_warm_s=warm_s
    )


def voice_manager(
    home: Path, kinds: Kinds, orchestrator: Orchestrator, bus: EventBus
) -> tuple[VoiceManager, asyncio.Event]:
    """Менеджер голосов: открытый голос уходит в оркестратор и взводит событие «голос есть»."""
    voice_ready = asyncio.Event()

    def on_voice(tts: TextToSpeech, kind: str, voice: str) -> None:
        orchestrator.use_tts(tts)
        voice_ready.set()

    return VoiceManager(home, kinds.tts, on_voice, events=bus), voice_ready


def control(
    parts: Assembly,
    home: Path,
    store: ConfigFile,
    ollama: Ollama,
    version: str,
    build: BuildAnswering,
    use_speech: Callable[[SpeechConfig], None],
) -> Core:
    """Пульт: разделы на лету, сведения для status и промпты из текущих настроек."""
    kinds, bus, hub, live, capabilities, tools = (
        parts.kinds,
        parts.bus,
        parts.hub,
        parts.live,
        parts.capabilities,
        parts.tools,
    )
    catalog = CloudCatalog()  # список моделей облачного сервиса для интерфейса (кэш)
    prompts = NetworkPrompts(  # настройки = живые части
        lambda: store.config.entry_executor().id,
        lambda: member_specs(store.config),
        lambda: prompt_stages(store.config, kinds),
        capabilities.known,
        lambda: live.executor,
        lambda: bool(tools.specs()),
    )
    return Core(
        store,
        live_sections(hub, parts.history, live, build, use_speech, tools),
        events=bus,
        feed=bus,
        voices=parts.voices,
        models=ollama.models,
        loaded=ollama.loaded,
        devices=hub.devices,
        version=version,
        validate=kinds_validator(kinds),  # иначе после перезапуска ядро не стартует
        dispatcher_prompt=prompts.entry,
        executor_prompts=prompts.all,
        supports_tools=capabilities.supports_tools,
        executor_states=lambda: live.members_warmth,
        connectors=tools.states,
        # ход через API: тот же путь, что с колонки, ответ текстом; человек — по связи с аккаунтом
        ask=lambda question: parts.orchestrator.ask(parts.people.identify(question)),
        decode=decode_audio,  # голосовое (OGG/Opus, WAV) → PCM для распознавания
        unload=ollama.unload,  # «Выгрузить» в интерфейсе: только модель, что сейчас в памяти
        cloud_models=lambda: catalog.models(store.config.cloud.base_url, store.config.cloud.api_key),
        lmstudio_models=lambda: fetch_lmstudio_models(
            store.config.lmstudio.base_url, store.config.lmstudio.api_key
        ),
        data_dir=str(home),
    )


def system_snapshot(tasks: TaskRegistry, tools: McpHub, hub: DeviceHub) -> SystemSnapshot:
    """Снимок для обработчика «система»: идущие задачи, готовые коннекторы, громкость колонок."""
    running = [(t.title, t.eta) for t in tasks.tasks() if t.status == "running"]
    skills = [c.name for c in tools.states() if c.state == "ready" and c.kind == "mcp"]
    return SystemSnapshot(running, skills, [(d.name, d.volume) for d in hub.devices() if d.connected])
