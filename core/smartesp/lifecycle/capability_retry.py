"""Повтор запроса возможностей моделей: Ollama поднялась позже ядра — сеть пересобирается."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from .answering import Answering, LiveAnswering

_log = logging.getLogger("smartesp")

CAPABILITY_RETRY_S = 15.0  # как часто спрашивать возможности моделей, неизвестные при сборке сети


@runtime_checkable
class _HasUnknownModels(Protocol):
    """Сеть исполнителей: модели, чьи возможности при сборке узнать не удалось."""

    def unknown_models(self) -> frozenset[str]: ...


class CapabilityRetry:
    """Пока у живой сети есть модели с неизвестными возможностями, спрашивает их снова.

    Если Ollama не была запущена при сборке сети, её модели считаются не умеющими
    инструменты и передача выключена. Как только возможности хоть одной такой
    модели стали известны, живая пара пересобирается тем же путём, что правка
    настроек (rebuild → use → release): старая сеть освобождается как обычно.
    """

    def __init__(
        self,
        live: LiveAnswering,
        capabilities: Callable[[str], Awaitable[frozenset[str]]],
        rebuild: Callable[[], Awaitable[Answering]],
        *,
        interval_s: float = CAPABILITY_RETRY_S,
    ) -> None:
        """capabilities(модель) — возможности (пусто — неизвестны); rebuild() — пара по текущим настройкам.

        interval_s — пауза между проверками, секунды.
        """
        self._live = live
        self._capabilities = capabilities
        self._rebuild = rebuild
        self._interval_s = interval_s

    async def run(self) -> None:
        """Проверяет каждые interval_s секунд, пока задачу не отменят."""
        while True:
            await asyncio.sleep(self._interval_s)
            await self.check()

    async def check(self) -> bool:
        """Одна проверка; True — живая пара пересобрана. Не бросает исключений, кроме отмены."""
        executor = self._live.executor
        unknown = sorted(executor.unknown_models()) if isinstance(executor, _HasUnknownModels) else []
        if not unknown:
            return False
        found = await asyncio.gather(*(self._capabilities(model) for model in unknown))
        learned = [model for model, caps in zip(unknown, found, strict=True) if caps]
        if not learned:
            return False
        _log.info("Возможности моделей %s известны: пересобираю сеть исполнителей", learned)
        try:
            return await self._live.rebuild(self._rebuild)
        except Exception:
            _log.warning("Пересборка сети исполнителей не удалась; повторю позже", exc_info=True)
            return False
