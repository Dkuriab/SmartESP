"""Договор: события ядра для ленты интерфейса."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CoreEvent:
    """Событие: вид, данные и время (time.time())."""

    kind: str
    data: dict[str, object]
    at: float


class EventSink(Protocol):
    """Приёмник событий: туда публикуют оркестратор и хаб устройств."""

    def publish(self, kind: str, data: dict[str, object]) -> None:
        """Публикует событие без ожидания; вызывается из цикла событий."""
        ...


class EventFeed(Protocol):
    """Лента событий для интерфейса."""

    def subscribe(self) -> AsyncIterator[CoreEvent]:
        """Подписывает на новые события; выход из цикла снимает подписку."""
        ...

    def recent_turns(self, limit: int) -> list[dict[str, object]]:
        """Возвращает данные последних завершённых ходов, от новых к старым."""
        ...
