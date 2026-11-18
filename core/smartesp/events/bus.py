"""Шина событий: подписчики с ограниченными очередями и память о ходах."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from smartesp.contracts import CoreEvent, Subscription

TURN_FINISHED = "turn_finished"


class EventBus:
    """Рассылает события подписчикам; реализует EventSink и EventFeed."""

    def __init__(
        self,
        max_turns: int = 100,
        queue_size: int = 1000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size должен быть больше нуля")
        self._queue_size = queue_size
        self._clock = clock
        self._queues: set[asyncio.Queue[CoreEvent]] = set()
        self._turns: deque[dict[str, object]] = deque(maxlen=max_turns)

    @property
    def subscriber_count(self) -> int:
        """Число активных подписчиков."""
        return len(self._queues)

    def publish(self, kind: str, data: dict[str, object]) -> None:
        """Раздаёт событие всем подписчикам, не ожидая; у медленного
        подписчика при переполнении выбрасывается самое старое событие."""
        event = CoreEvent(kind=kind, data=dict(data), at=self._clock())
        if kind == TURN_FINISHED:
            self._turns.append(event.data)
        for queue in self._queues:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def subscribe(self) -> Subscription:
        """Подписывает сразу при вызове; подписку нужно закрыть через aclose()."""
        queue: asyncio.Queue[CoreEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        return _BusSubscription(queue, lambda: self._queues.discard(queue))

    def recent_turns(self, limit: int) -> list[dict[str, object]]:
        """Возвращает данные последних ходов, от новых к старым."""
        if limit <= 0:
            return []
        return list(reversed(self._turns))[:limit]


class _BusSubscription:
    """Подписка: снимается при aclose() и при отмене ожидания."""

    def __init__(self, queue: asyncio.Queue[CoreEvent], unregister: Callable[[], object]) -> None:
        self._queue = queue
        self._unregister = unregister
        self._closed = False

    def __aiter__(self) -> _BusSubscription:
        return self

    async def __anext__(self) -> CoreEvent:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        """Снимает подписку; повторный вызов безопасен."""
        self._closed = True
        self._unregister()
