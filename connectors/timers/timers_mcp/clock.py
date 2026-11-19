"""Часы коннектора: настоящие и договор для подделки в тестах."""

from datetime import datetime
from typing import Protocol

import anyio


class Clock(Protocol):
    """Источник времени: «сейчас» и ожидание до момента."""

    def now(self) -> datetime:
        """Текущее местное время с часовым поясом."""
        ...

    def local(self, naive: datetime) -> datetime:
        """Местное время без пояса → с поясом этого момента (учитывает летнее время)."""
        ...

    async def sleep_until(self, deadline: datetime) -> None:
        """Ждёт, пока не наступит `deadline` (если уже наступил — сразу возвращается)."""
        ...


class SystemClock:
    """Настоящие часы Mac: местное время системы."""

    def now(self) -> datetime:
        """Текущее местное время с часовым поясом системы."""
        return datetime.now().astimezone()

    def local(self, naive: datetime) -> datetime:
        """Пояс системы на момент `naive` (системный mktime учитывает переход времени)."""
        return naive.astimezone()

    async def sleep_until(self, deadline: datetime) -> None:
        """Спит до `deadline` по настоящему времени."""
        await anyio.sleep(max(0.0, (deadline - self.now()).total_seconds()))
