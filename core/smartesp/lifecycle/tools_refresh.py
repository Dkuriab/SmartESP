"""Пересборка сети исполнителей, когда изменился список инструментов коннекторов."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .answering import Answering, LiveAnswering

_log = logging.getLogger("smartesp")

TOOLS_DEBOUNCE_S = 2.0  # не чаще одной пересборки за столько секунд


class ToolsRefresh:
    """Коннектор стал готов, упал или выключен — живая сеть пересобирается с новыми инструментами.

    Сеть берёт снимок инструментов при сборке, поэтому смену списка надо донести
    пересборкой — тем же путём, что правка настроек (rebuild → use → release).
    Смены, пришедшие пачкой (коннекторы стартуют почти вместе), дают одну
    пересборку после паузы debounce_s. Пока стартовая сеть не поставлена,
    пересборка откладывается: смена не теряется.
    """

    def __init__(
        self,
        live: LiveAnswering,
        rebuild: Callable[[], Awaitable[Answering]],
        *,
        debounce_s: float = TOOLS_DEBOUNCE_S,
    ) -> None:
        """rebuild() — пара по текущим настройкам и текущим инструментам; debounce_s — пауза, секунды."""
        self._live = live
        self._rebuild = rebuild
        self._debounce_s = debounce_s
        self._dirty = asyncio.Event()

    def changed(self) -> None:
        """Список инструментов изменился (зовёт хаб); пересборка — в run."""
        self._dirty.set()

    async def run(self) -> None:
        """Пересобирает сеть после смен, пока задачу не отменят; сбой пересборки — в журнал."""
        while True:
            await self._dirty.wait()
            await asyncio.sleep(self._debounce_s)
            if self._live.executor is None:
                continue  # стартовая сеть ещё собирается: пересоберём, когда она встанет
            self._dirty.clear()
            await self._refresh()

    async def _refresh(self) -> None:
        _log.info("Инструменты коннекторов изменились: пересобираю сеть исполнителей")
        try:
            rebuilt = await self._live.rebuild(self._rebuild)
        except Exception:
            _log.warning("Сеть исполнителей не пересобрана под новые инструменты", exc_info=True)
            return
        if not rebuilt:
            self._dirty.set()  # живую сменила правка: проверим ещё раз с текущими инструментами
