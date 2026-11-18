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


class Subscription(Protocol):
    """Подписка на ленту: асинхронный итератор, который нужно закрывать."""

    def __aiter__(self) -> AsyncIterator[CoreEvent]: ...

    async def __anext__(self) -> CoreEvent:
        """Ждёт следующее событие."""
        ...

    async def aclose(self) -> None:
        """Снимает подписку; повторный вызов безопасен."""
        ...


class EventFeed(Protocol):
    """Лента событий для интерфейса."""

    def subscribe(self) -> Subscription:
        """Подписывает на новые события с момента вызова.

        Потребитель обязан закрыть подписку: `async with aclosing(feed.subscribe())`.
        """
        ...

    def recent_turns(self, limit: int) -> list[dict[str, object]]:
        """Возвращает данные последних завершённых ходов, от новых к старым."""
        ...
