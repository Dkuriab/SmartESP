"""Ожидание итога открытия голоса без его отмены (внутренний модуль менеджера)."""

import asyncio


async def result_of(fut: "asyncio.Future[bool]") -> bool:
    """Ждёт итог, не отменяя его; отмена самого итога (не ждущего) — False."""
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        me = asyncio.current_task()
        if me is not None and me.cancelling():
            raise
        return False
