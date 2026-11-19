"""Пересборка сети исполнителей, когда изменился список инструментов коннекторов."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

_log = logging.getLogger("smartesp")

TOOLS_DEBOUNCE_S = 2.0  # не чаще одной пересборки за столько секунд
TOOLS_RETRY_S = 15.0  # пауза после первой неудачной пересборки
MAX_TOOLS_RETRY_S = 300.0  # потолок паузы после неудачных пересборок


class ToolsRefresh:
    """Коннектор стал готов, упал или выключен — живая сеть пересобирается с новыми инструментами.

    Сеть берёт снимок инструментов при сборке, поэтому смену списка надо донести
    пересборкой. rebuild() идёт через очередь правок настроек: так пересборка не
    гоняется с правкой и берёт уже записанные настройки и текущие инструменты.
    Смены, пришедшие пачкой (коннекторы стартуют почти вместе), дают одну
    пересборку после паузы debounce_s. Пока стартовая сеть не поставлена
    (ready() ложно), пересборка откладывается. Неудачная пересборка повторяется
    после паузы retry_s, растущей вчетверо до max_retry_s (15 → 60 → 240 → 300 с);
    смена снимается только удачной пересборкой.
    """

    def __init__(
        self,
        ready: Callable[[], bool],
        rebuild: Callable[[], Awaitable[None]],
        *,
        debounce_s: float = TOOLS_DEBOUNCE_S,
        retry_s: float = TOOLS_RETRY_S,
        max_retry_s: float = MAX_TOOLS_RETRY_S,
    ) -> None:
        """ready() — стартовая сеть стоит; rebuild() — пересборка (ошибка — исключение)."""
        self._ready = ready
        self._rebuild = rebuild
        self._debounce_s = debounce_s
        self._retry_s = retry_s
        self._max_retry_s = max(max_retry_s, retry_s)
        self._dirty = asyncio.Event()
        self._failures = 0  # неудачных пересборок подряд

    def changed(self) -> None:
        """Список инструментов изменился (зовёт хаб); пересборка — в run."""
        self._dirty.set()

    async def run(self) -> None:
        """Пересобирает сеть после смен, пока задачу не отменят; сбой — повтор с паузой."""
        while True:
            await self._dirty.wait()
            await asyncio.sleep(self._debounce_s)
            if not self._ready():
                continue  # стартовая сеть ещё собирается: пересоберём, когда она встанет
            self._dirty.clear()  # смены во время пересборки взведут его снова
            if not await self._refresh():
                self._dirty.set()
                await asyncio.sleep(self.delay_s())

    def delay_s(self) -> float:
        """Пауза перед повтором после неудачных пересборок, секунды."""
        return min(self._retry_s * 4 ** max(self._failures - 1, 0), self._max_retry_s)

    async def _refresh(self) -> bool:
        _log.info("Инструменты коннекторов изменились: пересобираю сеть исполнителей")
        try:
            await self._rebuild()
        except Exception:
            self._failures += 1
            level = logging.WARNING if self._failures == 1 else logging.DEBUG
            _log.log(level, "Сеть исполнителей не пересобрана под новые инструменты", exc_info=True)
            return False
        self._failures = 0
        return True
