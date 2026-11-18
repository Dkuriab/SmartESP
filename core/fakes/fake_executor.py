"""Подделка исполнителя: отдаёт заданные куски, может упасть или тянуть время."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from smartesp.contracts.executor import ChatMessage, ReplyPart


class FakeExecutor:
    def __init__(self, parts: list[str], error: Exception | None = None, delay: float = 0) -> None:
        self._parts = parts
        self._error = error
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []  # сообщения каждого вызова run

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        for part in self._parts:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield ReplyPart(part)
