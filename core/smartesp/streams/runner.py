"""Переходы очереди колонки: начать элемент новым потоком, пауза, стоп, следующий по отчёту, сторож.

Всё, что меняет очередь, идёт под замком колонки (lock): действия владельца и переходы по отчётам
колонки не перемешиваются.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import Any

from smartesp.contracts import (
    STREAM_RATE,
    StreamAction,
    StreamCommand,
    StreamItem,
    StreamLink,
    StreamRefused,
)

from . import texts
from .queue import SpeakerQueue, Ticket
from .sources import is_capture, is_live, title_of

_log = logging.getLogger(__name__)

PATH = "/device/stream/"  # ссылка колонки на ядре (без токена API)
MAX_FAILURES = 3
TICKET_TTL_S = 30.0  # ссылка живёт до открытия


class Runner:
    """Переходы очередей; publish(очередь) — сообщить об изменении, queue_of(колонка) — её очередь,
    check(колонка) — StreamRefused, если колонка не в сети или не умеет потоки."""

    def __init__(
        self,
        link: StreamLink,
        queue_of: Callable[[str], SpeakerQueue | None],
        publish: Callable[[SpeakerQueue], None],
        check: Callable[[str], None],
        *,
        clock: Callable[[], float],
        start_timeout_s: float,
        stop_wait_s: float,
    ) -> None:
        self._link = link
        self._queue_of = queue_of
        self._publish = publish
        self._check = check
        self._clock = clock
        self._start_timeout_s = start_timeout_s
        self._stop_wait_s = stop_wait_s
        self._tickets: dict[str, Ticket] = {}
        self._ids = itertools.count(1)
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def lock(self, device_id: str) -> asyncio.Lock:
        """Замок очереди колонки."""
        return self._locks.setdefault(device_id, asyncio.Lock())

    def take_ticket(self, token: str) -> Ticket | None:
        """Ссылка по токену (одноразово); нет или истекла — None."""
        now = self._clock()
        for stale in [t for t, ticket in self._tickets.items() if ticket.until <= now]:
            del self._tickets[stale]
        return self._tickets.pop(token, None)

    async def act(self, queue: SpeakerQueue, action: StreamAction) -> None:
        """Действие владельца (под замком колонки)."""
        if action == "pause":
            if queue.state == "playing":
                await self.pause(queue)
        elif action == "resume":
            if queue.state == "paused":
                self._check(queue.device_id)
                await self.start(queue, queue.index, queue.resume_s)
        elif action == "next" and queue.index + 1 >= len(queue.items):
            await self.halt(queue, "")
        elif action in ("next", "previous"):
            self._check(queue.device_id)
            step = 1 if action == "next" else -1
            await self.start(queue, max(queue.index + step, 0), 0.0)
        elif action == "stop":
            await self.halt(queue, "")

    async def start(self, queue: SpeakerQueue, index: int, start_s: float) -> None:
        """Отдаёт колонке элемент index с start_s новым потоком; не ушло — пауза и StreamRefused."""
        queue.index = index
        item = queue.items[index]
        queue.offset_s = 0.0 if is_live(item.source) else max(start_s, 0.0)
        queue.played, queue.reported, queue.error, queue.stopped = 0, False, "", None
        queue.stream = next(self._ids)
        token = secrets.token_urlsafe(24)
        until = self._clock() + TICKET_TTL_S
        self._tickets[token] = Ticket(queue.device_id, queue.stream, item.source, queue.offset_s, until)
        live = is_live(item.source)
        command = StreamCommand("start", queue.stream, PATH + token, STREAM_RATE, queue.volume, live)
        queue.state = "playing"
        if not await self._link.send_stream(queue.device_id, command):
            self._tickets.pop(token, None)
            self.paused(queue, texts.OFFLINE)
            raise StreamRefused("offline", texts.OFFLINE)
        self._publish(queue)
        self.spawn(self._watchdog(queue.device_id, queue.stream))

    async def pause(self, queue: SpeakerQueue) -> None:
        """Стоп на колонке с ожиданием отчёта stopped (по нему — точная позиция), затем пауза."""
        queue.stopped = asyncio.Event()
        if await self._link.send_stream(queue.device_id, StreamCommand("stop", queue.stream)):
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(queue.stopped.wait(), self._stop_wait_s)
        self.paused(queue, "")

    def paused(self, queue: SpeakerQueue, error: str) -> None:
        """Пауза с запомненной позицией (у живого потока — с начала)."""
        queue.resume_s = 0.0 if queue.live else queue.position_s()
        queue.state, queue.stream, queue.stopped, queue.error = "paused", 0, None, error
        self._publish(queue)

    async def halt(self, queue: SpeakerQueue, error: str) -> None:
        """Стоп: поток на колонке останавливается, очередь пуста; error — почему ("" — просто стоп)."""
        if queue.stream:
            await self._link.send_stream(queue.device_id, StreamCommand("stop", queue.stream))
        queue.state, queue.stream, queue.error = "idle", 0, error
        self._publish(queue)

    async def after(self, device_id: str, stream: int, error: str) -> None:
        """Поток кончился (error "") или сломался: следующий элемент, пропуск или стоп."""
        queue = self._queue_of(device_id)
        if queue is None:
            return
        async with self.lock(device_id):
            if self._queue_of(device_id) is not queue or queue.stream != stream:
                return
            item = queue.item
            if error == "rate":
                await self.halt(queue, texts.RATE)
                return
            if error:
                queue.failures += 1
                if queue.failures >= MAX_FAILURES or len(queue.items) == 1 or item is None:
                    await self.halt(queue, _broken(item))
                    return
            if queue.index + 1 >= len(queue.items):
                queue.state, queue.stream = "idle", 0  # очередь доиграна
                self._publish(queue)
                return
            with contextlib.suppress(StreamRefused):
                await self.start(queue, queue.index + 1, 0.0)

    async def _watchdog(self, device_id: str, stream: int) -> None:
        """Колонка не отчиталась о потоке за start_timeout_s — стоп с ошибкой."""
        await asyncio.sleep(self._start_timeout_s)
        queue = self._queue_of(device_id)
        if queue is None or queue.stream != stream or queue.reported:
            return
        async with self.lock(device_id):
            if queue.stream == stream and not queue.reported:
                _log.warning("Колонка %s не начала поток %d", device_id, stream)
                await self.halt(queue, texts.NO_START)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Фоновая задача; её сбой — в журнал."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def done(t: asyncio.Task[None]) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                _log.error("Поток: фоновая задача упала", exc_info=t.exception())

        task.add_done_callback(done)

    async def aclose(self) -> None:
        """Снимает фоновые задачи."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _broken(item: StreamItem | None) -> str:
    """Почему очередь остановлена на сломанном элементе (у звука Mac — подсказка про доступ)."""
    if item is not None and is_capture(item.source):
        return texts.CAPTURE_BROKEN
    return texts.BROKEN.format(title=(item.title or title_of(item.source)) if item else "")
