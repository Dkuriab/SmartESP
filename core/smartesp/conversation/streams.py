"""Потоки хода: закрытие итераторов, пустой звук и ожидание кусков исполнителя с таймаутами."""

import asyncio
import itertools
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from smartesp.contracts import ExecutorError, ReplyPart

_log = logging.getLogger(__name__)


@asynccontextmanager
async def closing[T](iterator: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    """Как contextlib.aclosing, но для любого AsyncIterator: закрывает его, если это генератор."""
    try:
        yield iterator
    finally:
        if isinstance(iterator, AsyncGenerator):
            await iterator.aclose()


async def no_audio() -> AsyncIterator[bytes]:
    """Пустой поток звука: хаб пошлёт reply_start + reply_end, колонка перестанет ждать."""
    for chunk in list[bytes]():
        yield chunk


async def first_part(
    parts: AsyncIterator[ReplyPart],
    keep_waiting: Callable[[], Awaitable[None]],
    interval_s: float,
    limit_s: float,
) -> ReplyPart | None:
    """Ждёт первый кусок ответа исполнителя.

    Пока ждём, вызывает keep_waiting каждые interval_s (впервые — через interval_s),
    чтобы колонка не бросила ожидание. Возвращает кусок или None, если исполнитель
    закончил, ничего не сказав. Нет куска за limit_s — ExecutorError (ожидание
    куска прерывается, генератор исполнителя дальше не годится).
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    ticker = asyncio.create_task(_tick(keep_waiting, interval_s, start))
    try:
        async with asyncio.timeout_at(start + limit_s):
            return await anext(parts, None)
    except TimeoutError as error:
        raise ExecutorError(f"исполнитель не ответил за {limit_s:g} с") from error
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)


async def next_part(parts: AsyncIterator[ReplyPart], idle_s: float) -> ReplyPart | None:
    """Следующий кусок ответа или None в конце; исполнитель молчит дольше idle_s — ExecutorError."""
    try:
        async with asyncio.timeout(idle_s):
            return await anext(parts, None)
    except TimeoutError as error:
        raise ExecutorError(f"исполнитель молчит дольше {idle_s:g} с") from error


async def _tick(callback: Callable[[], Awaitable[None]], interval_s: float, start: float) -> None:
    """Вызывает callback в моменты start + k·interval_s (k = 1, 2, …), пока задачу не отменят.

    Моменты считаются от start, а не от прошлого вызова: задержки не накапливаются.
    """
    loop = asyncio.get_running_loop()
    for k in itertools.count(1):
        await asyncio.sleep(max(0.0, start + k * interval_s - loop.time()))
        try:
            await callback()
        except Exception:
            _log.warning("Сигнал ожидания колонке не отправлен", exc_info=True)
