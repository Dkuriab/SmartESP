"""Шина событий: подписчики с ограниченными очередями и память о ходах."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable

from smartesp.contracts import CoreEvent

TURN_FINISHED = "turn_finished"


class EventBus:
    """Рассылает события подписчикам; реализует EventSink и EventFeed."""

    def __init__(
        self,
        max_turns: int = 100,
        queue_size: int = 1000,
        clock: Callable[[], float] = time.time,
    ) -> None:
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
        event = CoreEvent(kind=kind, data=data, at=self._clock())
        if kind == TURN_FINISHED:
            self._turns.append(data)
        for queue in self._queues:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def subscribe(self) -> AsyncIterator[CoreEvent]:
        """Подписывает сразу при вызове; подписка снимается при закрытии итератора."""
        queue: asyncio.Queue[CoreEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        return self._iterate(queue)

    async def _iterate(self, queue: asyncio.Queue[CoreEvent]) -> AsyncIterator[CoreEvent]:
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues.discard(queue)

    def recent_turns(self, limit: int) -> list[dict[str, object]]:
        """Возвращает данные последних ходов, от новых к старым."""
        return list(reversed(self._turns))[:limit]
