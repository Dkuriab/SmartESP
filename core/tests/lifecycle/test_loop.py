"""Цикл процесса: не ждёт зависших потоков пула при выходе."""

from __future__ import annotations

import asyncio
import threading
import time

from smartesp.lifecycle import run_loop


def test_run_loop_does_not_wait_for_stuck_thread() -> None:
    stuck = threading.Event()

    async def work() -> int:
        asyncio.create_task(asyncio.to_thread(stuck.wait))
        await asyncio.sleep(0.01)
        return 5

    started = time.monotonic()
    try:
        assert run_loop(work()) == 5
        assert time.monotonic() - started < 1.0
    finally:
        stuck.set()


def test_run_loop_cancels_leftover_tasks() -> None:
    cancelled: list[bool] = []

    async def forever() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def work() -> None:
        asyncio.create_task(forever())
        await asyncio.sleep(0.01)

    run_loop(work())
    assert cancelled == [True]
