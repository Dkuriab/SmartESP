"""Поддельные часы: время двигает тест, реального ожидания нет."""

from datetime import datetime, timedelta

import anyio


class FakeClock:
    """Часы, которые стоят, пока тест не вызовет `advance`."""

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._moved = anyio.Event()

    def now(self) -> datetime:
        """Текущее поддельное время."""
        return self._now

    def local(self, naive: datetime) -> datetime:
        """Поддельный местный пояс — пояс стартового времени."""
        return naive.replace(tzinfo=self._now.tzinfo)

    async def sleep_until(self, deadline: datetime) -> None:
        """Ждёт, пока поддельное время не дойдёт до `deadline`."""
        while self._now < deadline:
            await self._moved.wait()

    def advance(self, seconds: float) -> None:
        """Сдвигает время вперёд и будит ждущих."""
        self._now += timedelta(seconds=seconds)
        moved, self._moved = self._moved, anyio.Event()
        moved.set()
