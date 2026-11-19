"""Возможности моделей Ollama (completion, tools…) с запоминанием на время процесса."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

_log = logging.getLogger("smartesp")

TOOLS = "tools"  # возможность модели вызывать инструменты


class CapabilityCache:
    """Запоминает возможности модели по имени на время процесса.

    Пустой ответ (Ollama недоступна, модели нет) не запоминается: модель могут
    скачать позже, тогда следующий запрос спросит Ollama снова.
    """

    def __init__(self, fetch: Callable[[str], Awaitable[frozenset[str]]]) -> None:
        """fetch(модель) — возможности модели из Ollama (model_capabilities)."""
        self._fetch = fetch
        self._known: dict[str, frozenset[str]] = {}

    async def get(self, model: str) -> frozenset[str]:
        """Возможности модели; сбой fetch — пустое множество и предупреждение в журнале."""
        return await self._get(model, logging.WARNING)

    async def probe(self, model: str) -> frozenset[str]:
        """Как get, но сбой fetch пишется только в отладочный журнал: для частых повторов."""
        return await self._get(model, logging.DEBUG)

    async def _get(self, model: str, failure_level: int) -> frozenset[str]:
        if model in self._known:
            return self._known[model]
        try:
            found = await self._fetch(model)
        except Exception:  # noqa: BLE001 — сбой Ollama не должен ломать сборку и API
            _log.log(failure_level, "Возможности модели %s не получены", model, exc_info=True)
            return frozenset()
        if found:
            self._known[model] = found
        return found

    def known(self, model: str) -> frozenset[str]:
        """Уже известные возможности модели без запроса к Ollama (неизвестно — пусто)."""
        return self._known.get(model, frozenset())

    async def supports_tools(self, model: str) -> bool:
        """True, если модель умеет вызывать инструменты."""
        return TOOLS in await self.get(model)
