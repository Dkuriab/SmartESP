"""Пульт ядра: состояние, сводка status, изменения настроек, голоса и перезапуск."""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from smartesp.contracts import (
    Answer,
    AskUnavailable,
    ChangeResult,
    ConfigStore,
    ConnectorState,
    DeviceInfo,
    EventFeed,
    EventSink,
    Question,
    Section,
    VoicePort,
)

from .changes import RESTART_SECTIONS, STOPPING, ChangeQueue
from .ollama import model_list, no_unload, ollama_state, unload_loaded

_log = logging.getLogger(__name__)

STATES = ("warming", "ready", "stopping")


async def _no_cloud() -> list[dict[str, Any]]:
    return []


async def _no_tools(model: str) -> bool:
    """По умолчанию модели считаются не умеющими инструменты."""
    return False


async def _no_asking(question: Question) -> Answer:
    """По умолчанию ходов через API нет."""
    raise AskUnavailable("ходы через API не подключены")


async def _no_decoding(audio: bytes) -> bytes:
    """По умолчанию звук не разбирается."""
    raise AskUnavailable("разбор звука не подключён")


class Core:
    """Реализует CorePort: всё, что нужно API, плюс состояние ядра и просьба о перезапуске.

    Не импортирует другие модули: части и сведения приходят функциями от main.py.
    Ядро стартует в состоянии warming.
    """

    def __init__(
        self,
        store: ConfigStore,
        sections: Mapping[str, Section],
        *,
        events: EventSink,
        feed: EventFeed,
        voices: VoicePort,
        models: Callable[[], Awaitable[list[tuple[str, int]]]],
        loaded: Callable[[], Awaitable[list[str]]],
        devices: Callable[[], list[DeviceInfo]],
        version: str,
        clock: Callable[[], float] = time.monotonic,
        validate: Callable[[Any], None] | None = None,
        dispatcher_prompt: Callable[[], str] = str,
        executor_prompts: Callable[[], Mapping[str, str]] = dict,
        supports_tools: Callable[[str], Awaitable[bool]] = _no_tools,
        executor_states: Callable[[], Mapping[str, str | None]] = dict,
        connectors: Callable[[], Sequence[ConnectorState]] = list,
        ask: Callable[[Question], Awaitable[Answer]] = _no_asking,
        decode: Callable[[bytes], Awaitable[bytes]] = _no_decoding,
        unload: Callable[[str], Awaitable[None]] = no_unload,
        cloud_models: Callable[[], Awaitable[list[dict[str, Any]]]] = _no_cloud,
        data_dir: str = "",
    ) -> None:
        """validate(настройки) — проверка правки целиком; ValueError — status invalid.

        dispatcher_prompt() — итоговый промпт входного исполнителя (с правилами обработчиков);
        executor_prompts() — итоговые промпты всех исполнителей по id;
        supports_tools(модель) — умеет ли модель инструменты (для списка моделей);
        executor_states() — итог фонового прогрева исполнителей: {id: None — готов, иначе ошибка};
        connectors() — состояния MCP-коннекторов в порядке настроек;
        ask(вопрос) — ход через API; decode(звук) — OGG/Opus или WAV в PCM 16 кГц моно;
        unload(модель) — выгрузить модель из памяти Ollama; data_dir — папка данных (для info);
        cloud_models() — модели облачного сервиса (сбой — ExecutorError).
        """
        self._store = store
        self._events = events
        self._feed = feed
        self._voices = voices
        self._models = models
        self._loaded = loaded
        self._devices = devices
        self._version = version
        self._dispatcher_prompt = dispatcher_prompt
        self._executor_prompts = executor_prompts
        self._supports_tools = supports_tools
        self._executor_states = executor_states
        self._connectors = connectors
        self._ask = ask
        self._decode = decode
        self._unload = unload
        self.cloud_models = cloud_models  # GET /cloud/models: [{id, name, tools, prompt_price, …}]
        self._data_dir = data_dir
        self._clock = clock
        self._started = clock()
        self._state = "warming"
        self._ids = itertools.count(1)
        self._changes = ChangeQueue(store, sections, voices=voices, events=events, validate=validate)
        self._restart = asyncio.Event()
        self._stop = asyncio.Event()
        self._downloads: set[asyncio.Task[None]] = set()

    # ---- состояние и перезапуск ----

    @property
    def state(self) -> str:
        """Текущее состояние ядра: warming, ready или stopping."""
        return self._state

    def set_state(self, state: str) -> None:
        """Меняет состояние и публикует core_state; неизвестное состояние — ValueError."""
        if state not in STATES:
            raise ValueError(f"неизвестное состояние ядра: {state}")
        self._state = state
        self._events.publish("core_state", {"state": state})

    @property
    def restart_requested(self) -> bool:
        """True, если перезапуск уже попросили."""
        return self._restart.is_set()

    def request_restart(self) -> None:
        """Просит перезапуск: будит wait_restart()."""
        self._restart.set()

    async def wait_restart(self) -> None:
        """Ждёт просьбы о перезапуске."""
        await self._restart.wait()

    @property
    def stop_requested(self) -> bool:
        """True, если попросили остановку с выходом (она важнее перезапуска)."""
        return self._stop.is_set()

    def request_stop(self) -> None:
        """Просит остановку с выходом: будит wait_stop()."""
        self._stop.set()

    async def wait_stop(self) -> None:
        """Ждёт просьбы об остановке."""
        await self._stop.wait()

    def info(self) -> dict[str, Any]:
        """Сведения о ядре: version, uptime_s, state, data_dir."""
        uptime = self._clock() - self._started
        return {
            "version": self._version,
            "uptime_s": uptime,
            "state": self._state,
            "data_dir": self._data_dir,
        }

    async def aclose(self) -> None:
        """Останавливает очередь изменений (текущее отменяется) и фоновые скачивания."""
        await self._changes.aclose()
        pending = list(self._downloads)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # ---- CorePort ----

    async def status(self) -> dict[str, Any]:
        """Сводка: version, uptime_s, state, ollama, devices, voice, applying, restart_required,
        executors, connectors.

        executors — [{id, ready, error}] исполнителей, чей фоновый прогрев закончился;
        connectors — как в connectors(), но без settings (сводку опрашивают часто).
        """
        return {
            "version": self._version,
            "uptime_s": self._clock() - self._started,
            "state": self._state,
            "ollama": await ollama_state(self._loaded),
            "devices": [dataclasses.asdict(device) for device in self._devices()],
            "voice": self._voices.state(),
            "applying": self._changes.applying,
            "restart_required": self._changes.restart_required,
            "executors": [
                {"id": executor_id, "ready": error is None, "error": error}
                for executor_id, error in self._executor_states().items()
            ],
            "connectors": self._connector_states(),
        }

    def _connector_states(self) -> list[dict[str, Any]]:
        return [{**dataclasses.asdict(c), "tools": list(c.tools)} for c in self._connectors()]

    def connectors(self) -> list[dict[str, Any]]:
        """Коннекторы: [{id, name, state, tools, error, settings, note, example}] в порядке настроек.

        settings — объявленные коннектором настройки с текущими значениями (секреты скрыты);
        note и example — его пояснение и пример для config.yaml (нет — пустые строки).
        """
        declared = self._store.connector_settings()
        empty = {"settings": [], "note": "", "example": ""}
        return [{**item, **empty, **declared.get(item["id"], {})} for item in self._connector_states()]

    def config(self) -> dict[str, Any]:
        """Действующие настройки, ключи владельца, разделы с перезапуском и итоговые промпты."""
        return {
            "effective": self._store.effective(),
            "overridden": self._store.overridden(),
            "restart_sections": list(RESTART_SECTIONS),
            "dispatcher_prompt": self._dispatcher_prompt(),
            "executor_prompts": dict(self._executor_prompts()),
        }

    async def patch_config(self, patch: dict[str, Any]) -> ChangeResult:
        """Проверяет правку и ставит в очередь: accepted, restart_required или invalid.

        После остановки (aclose) — stopping с текстом «ядро останавливается».
        """
        return self._changes.submit(next(self._ids), patch)

    async def rebuild(self, sections: Sequence[str]) -> None:
        """Пересобирает разделы по записанным настройкам в очереди правок (после идущих правок).

        Ошибка сборки пробрасывается; после aclose — RuntimeError.
        """
        await self._changes.rebuild(sections)

    async def models(self) -> list[dict[str, Any]]:
        """Модели Ollama: [{name, size_bytes, supports_tools}]; Ollama недоступна — ExecutorError."""
        return await model_list(self._models, self._supports_tools)

    async def unload_model(self, name: str) -> None:
        """Выгружает модель из памяти Ollama.

        Нет в памяти — ModelNotLoadedError; Ollama недоступна — ExecutorError.
        """
        await unload_loaded(self._loaded, self._unload, name)

    def voices(self) -> list[dict[str, Any]]:
        """Каталог голосов в форме API."""
        return list(self._voices.catalog())

    async def download_voice(self, kind: str, voice: str) -> ChangeResult:
        """Запускает скачивание в фоне и сразу отвечает accepted.

        Ход и итог публикует менеджер голосов (voice_download, voice_ready);
        ошибка скачивания здесь только пишется в журнал. Голоса нет в каталоге —
        "invalid" с текстом ошибки, скачивание не начинается. После aclose — "stopping".
        """
        change_id = next(self._ids)
        if self._changes.closed:
            return ChangeResult(change_id, "stopping", STOPPING)
        if not any(v.get("kind") == kind and v.get("voice") == voice for v in self._voices.catalog()):
            return ChangeResult(change_id, "invalid", f"Неизвестный голос {kind}/{voice}")
        task = asyncio.create_task(self._download(kind, voice), name=f"voice-download-{change_id}")
        self._downloads.add(task)
        task.add_done_callback(self._downloads.discard)
        return ChangeResult(change_id, "accepted")

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        """Образец голоса в WAV; голос не скачан — VoiceNotDownloadedError."""
        return await self._voices.preview(kind, voice, style, text)

    def turns(self, limit: int) -> list[dict[str, object]]:
        """Последние ходы из ленты, от новых к старым."""
        return self._feed.recent_turns(limit)

    async def ask(self, question: Question) -> Answer:
        """Ход через API текстом; ядро не готово или останавливается — AskUnavailable."""
        return await self._ask(question)

    async def ask_voice(self, audio: bytes, person: str, source: str) -> Answer:
        """Голосовой ход: звук → PCM → ход; не разобрать — AudioUndecodable, нет ffmpeg — AskUnavailable."""
        pcm = await self._decode(audio)
        return await self._ask(Question(pcm=pcm, person=person, source=source))

    # ---- внутреннее ----

    async def _download(self, kind: str, voice: str) -> None:
        try:
            await self._voices.download(kind, voice)
        except Exception:
            _log.warning("Голос %s/%s не скачан", kind, voice, exc_info=True)
