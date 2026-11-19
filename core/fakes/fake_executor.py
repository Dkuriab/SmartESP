"""Подделка исполнителя: отдаёт заданные куски, может упасть или тянуть время."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from smartesp.contracts.executor import ChatMessage, ReplyPart, ToolSpec


class FakeExecutor:
    def __init__(self, parts: list[str], error: Exception | None = None, delay: float = 0) -> None:
        self._parts = parts
        self._error = error
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []  # сообщения каждого вызова run

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        for part in self._parts:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield ReplyPart(part)


class FakeOllama(FakeExecutor):
    """Исполнитель с моделью, прогревом и выгрузкой — как OllamaExecutor.

    warm_gate — прогрев ждёт, пока событие не взведут (None — не ждёт).
    """

    def __init__(
        self,
        parts: list[str],
        model: str = "model",
        *,
        delay: float = 0,
        warm_gate: asyncio.Event | None = None,
        prompt: str = "",
    ) -> None:
        super().__init__(parts, delay=delay)
        self.model = model
        self.prompt = prompt  # системный промпт из настроек (для проверок)
        self.warm_gate = warm_gate
        self.warmed = 0
        self.unloaded: list[float] = []  # таймауты вызовов unload

    async def warm_up(self) -> None:
        if self.warm_gate is not None:
            await self.warm_gate.wait()
        self.warmed += 1

    async def unload(self, timeout_s: float = 1.0) -> None:
        self.unloaded.append(timeout_s)
