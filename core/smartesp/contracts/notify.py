"""Договор: речь по инициативе ядра — очередь объявлений на колонки."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

# Вытеснение: перед объявлением на занятой колонке — остановить то, что можно прервать (файл);
# True — колонку освободили. Связка передаёт его очереди объявлений (FilePlayer.preempt).
Preempt = Callable[[str], Awaitable[bool]]

# Итог мягкого прерывания ответа: прерывать нечего (колонка слушает, ход думает, ответ начался
# позже объявления); ответ приостановлен на границе предложения — остаток можно продолжить;
# ответ договорён до конца сам — колонка освободилась.
Interruption = Literal["none", "paused", "finished"]

# Мягкое прерывание: interrupt(колонка, since) — ответ, звучащий на колонке с момента раньше since
# (time.monotonic() постановки объявления), перестаёт получать новые предложения; ждёт, пока колонка
# доиграет отправленное. Связка передаёт его очереди объявлений (Orchestrator.interrupt).
Interrupt = Callable[[str, float], Awaitable[Interruption]]


class Announcer(Protocol):
    """Очередь объявлений: ядро само говорит на колонке (реализует модуль notify)."""

    def say(self, device_id: str, text: str, source: str) -> None:
        """Ставит текст в очередь объявлений колонки device_id без ожидания доставки.

        source — кто говорит (id исполнителя; для ленты событий).
        """
        ...
