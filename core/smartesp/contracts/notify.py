"""Договор: речь по инициативе ядра — очередь объявлений на колонки."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

# Вытеснение: перед объявлением на занятой колонке — остановить то, что можно прервать (файл);
# True — колонку освободили. Связка передаёт его очереди объявлений (FilePlayback.stop_file).
Preempt = Callable[[str], Awaitable[bool]]


class Announcer(Protocol):
    """Очередь объявлений: ядро само говорит на колонке (реализует модуль notify)."""

    def say(self, device_id: str, text: str, source: str) -> None:
        """Ставит текст в очередь объявлений колонки device_id без ожидания доставки.

        source — кто говорит (id исполнителя; для ленты событий).
        """
        ...
