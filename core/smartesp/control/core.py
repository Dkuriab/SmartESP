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
    ChangeResult,
    ConfigStore,
    ConnectorState,
    DeviceInfo,
    EventFeed,
    EventSink,
    ExecutorError,
    Section,
    VoicePort,
)

from .changes import RESTART_SECTIONS, STOPPING, ChangeQueue

_log = logging.getLogger(__name__)

STATES = ("warming", "ready", "stopping")
OLLAMA_TIMEOUT_S = 2.0  # сколько status ждёт ответа Ollama о загруженных моделях


async def _no_tools(model: str) -> bool:
    """По умолчанию модели считаются не умеющими инструменты."""
    return False


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
    ) -> None:
        """validate(настройки) — проверка правки целиком; ValueError — status invalid.

        dispatcher_prompt() — итоговый промпт входного исполнителя (с правилами обработчиков);
        executor_prompts() — итоговые промпты всех исполнителей по id;
        supports_tools(модель) — умеет ли модель инструменты (для списка моделей);
        executor_states() — итог фонового прогрева исполнителей: {id: None — готов, иначе ошибка};
        connectors() — состояния MCP-коннекторов в порядке настроек.
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
        self._clock = clock
        self._started = clock()
        self._state = "warming"
        self._ids = itertools.count(1)
        self._changes = ChangeQueue(store, sections, voices=voices, events=events, validate=validate)
        self._restart = asyncio.Event()
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
        connectors — как в connectors().
        """
        return {
            "version": self._version,
            "uptime_s": self._clock() - self._started,
            "state": self._state,
            "ollama": await self._ollama(),
            "devices": [dataclasses.asdict(device) for device in self._devices()],
            "voice": self._voices.state(),
            "applying": self._changes.applying,
            "restart_required": self._changes.restart_required,
            "executors": [
                {"id": executor_id, "ready": error is None, "error": error}
                for executor_id, error in self._executor_states().items()
            ],
            "connectors": self.connectors(),
        }

    def connectors(self) -> list[dict[str, Any]]:
        """Коннекторы: [{id, name, state, tools, error}] в порядке настроек."""
        return [{**dataclasses.asdict(c), "tools": list(c.tools)} for c in self._connectors()]

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

    async def models(self) -> list[dict[str, Any]]:
        """Модели Ollama: [{name, size_bytes, supports_tools}]; Ollama недоступна — ExecutorError."""
        listed = await self._models()
        tools = await asyncio.gather(*(self._supports_tools(name) for name, _ in listed))
        return [
            {"name": name, "size_bytes": size, "supports_tools": ok}
            for (name, size), ok in zip(listed, tools, strict=True)
        ]

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

    # ---- внутреннее ----

    async def _ollama(self) -> dict[str, object]:
        try:
            async with asyncio.timeout(OLLAMA_TIMEOUT_S):
                loaded = await self._loaded()
        except (ExecutorError, TimeoutError):
            return {"reachable": False, "loaded": []}
        except Exception:  # status не должен падать из-за Ollama
            _log.warning("Ollama: список загруженных моделей не получен", exc_info=True)
            return {"reachable": False, "loaded": []}
        return {"reachable": True, "loaded": loaded}

    async def _download(self, kind: str, voice: str) -> None:
        try:
            await self._voices.download(kind, voice)
        except Exception:
            _log.warning("Голос %s/%s не скачан", kind, voice, exc_info=True)
