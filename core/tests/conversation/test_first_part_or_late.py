"""Тесты ожидания первого куска без отмены чтения: предел не убивает генератор исполнителя."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
from conversation_helpers import TIMEOUT

from smartesp.contracts import ReplyPart
from smartesp.conversation.streams import LateFirstPart, first_part_or_late


async def test_first_part_or_late_keeps_pending() -> None:
    gate = asyncio.Event()
    closed: list[bool] = []

    async def parts() -> AsyncGenerator[ReplyPart]:
        try:
            await gate.wait()
            yield ReplyPart("Ответ.")
        finally:
            closed.append(True)

    ticks: list[int] = []

    async def tick() -> None:
        ticks.append(1)

    stream = parts()
    with pytest.raises(LateFirstPart) as caught:
        await first_part_or_late(stream, tick, 0.05, 0.12)
    pending = caught.value.pending
    assert ticks == [1, 1]
    assert not pending.done()
    await asyncio.sleep(0.05)
    assert ticks == [1, 1]  # после предела «думаю» больше не шлём
    gate.set()
    assert await asyncio.wait_for(pending, TIMEOUT) == ReplyPart("Ответ.")
    assert closed == []  # генератор жив
    await stream.aclose()
    assert closed == [True]


async def test_first_part_or_late_in_time() -> None:
    async def parts() -> AsyncIterator[ReplyPart]:
        yield ReplyPart("Сразу.")

    async def tick() -> None:
        pass

    assert await first_part_or_late(parts(), tick, 0.05, 1) == ReplyPart("Сразу.")


async def test_first_part_or_late_cancel_cancels_read() -> None:
    closed: list[bool] = []

    async def parts() -> AsyncIterator[ReplyPart]:
        try:
            await asyncio.sleep(10)
            yield ReplyPart("Поздно.")
        finally:
            closed.append(True)

    async def tick() -> None:
        pass

    task = asyncio.create_task(first_part_or_late(parts(), tick, 0.05, 5))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True]  # ожидание куска отменено вместе с генератором
