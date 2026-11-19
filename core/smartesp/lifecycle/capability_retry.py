"""Повтор запроса возможностей моделей: Ollama поднялась позже ядра — сеть пересобирается."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from .answering import Answering, LiveAnswering

_log = logging.getLogger("smartesp")

CAPABILITY_RETRY_S = 15.0  # как часто спрашивать возможности моделей, неизвестные при сборке сети
MAX_RETRY_S = 300.0  # потолок паузы после неудачных пересборок


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
        self._failures = 0  # неудачных пересборок подряд для одной и той же живой пары
        self._failed_executor: object | None = None

    async def run(self) -> None:
        """Проверяет, пока задачу не отменят; пауза — delay_s()."""
        while True:
            await asyncio.sleep(self.delay_s())
            await self.check()

    def delay_s(self) -> float:
        """Пауза до следующей проверки, секунды.

        Обычно interval_s; после неудачных пересборок растёт вчетверо (15 → 60 → 240 → 300)
        до MAX_RETRY_S, чтобы не прогревать незагружающуюся модель каждые 15 с.
        Сбрасывается, когда живая пара сменилась (правка настроек) или пересборка удалась.
        """
        if self._failed_executor is not self._live.executor:
            self._failures = 0
        return min(self._interval_s * 4**self._failures, max(MAX_RETRY_S, self._interval_s))

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
            rebuilt = await self._live.rebuild(self._rebuild)
        except Exception:
            self._failed(executor)
            return False
        self._failures = 0
        return rebuilt

    def _failed(self, executor: object) -> None:
        """Считает неудачу; предупреждает только о первой подряд, дальше — в отладочный журнал."""
        if self._failed_executor is not executor:
            self._failed_executor, self._failures = executor, 0
        self._failures += 1
        level = logging.WARNING if self._failures == 1 else logging.DEBUG
        _log.log(level, "Пересборка сети исполнителей не удалась; повторю позже", exc_info=True)
