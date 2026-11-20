"""Подделка исполнителя: отдаёт заданные куски, может упасть или тянуть время."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence

from smartesp.contracts.executor import ChatMessage, ReplyPart, ToolSpec


class FakeExecutor:
    """Отдаёт готовый сценарий: строка — кусок текста, ReplyPart — кусок как есть.

    error — бросается после error_after кусков (по умолчанию сразу).
    """

    def __init__(
        self,
        parts: Sequence[str | ReplyPart],
        error: Exception | None = None,
        delay: float = 0,
        *,
        error_after: int = 0,
    ) -> None:
        self._parts = parts
        self._error = error
        self._error_after = error_after
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []  # сообщения каждого вызова run
        self.tools: list[tuple[ToolSpec, ...]] = []  # инструменты каждого вызова run
        self.closed_early = False  # поток закрыли, не дочитав сценарий

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(messages)
        self.tools.append(tuple(tools))
        try:
            for index, part in enumerate(self._parts):
                if self._error is not None and index == self._error_after:
                    raise self._error
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield part if isinstance(part, ReplyPart) else ReplyPart(part)
        except (GeneratorExit, asyncio.CancelledError):
            self.closed_early = True
            raise
        if self._error is not None:
            raise self._error


class FakeOllama(FakeExecutor):
    """Исполнитель с моделью, прогревом и выгрузкой — как OllamaExecutor.

    warm_gate — прогрев ждёт, пока событие не взведут (None — не ждёт);
    warm_error — прогрев бросает это исключение (None — прогрев удачный).
    """

    def __init__(
        self,
        parts: Sequence[str | ReplyPart],
        model: str = "model",
        *,
        delay: float = 0,
        warm_gate: asyncio.Event | None = None,
        prompt: str = "",
        warm_error: Exception | None = None,
    ) -> None:
        super().__init__(parts, delay=delay)
        self.model = model
        self.prompt = prompt  # системный промпт из настроек (для проверок)
        self.warm_gate = warm_gate
        self.warm_error = warm_error
        self.warmed = 0
        self.unloaded: list[float] = []  # таймауты вызовов unload
        self.thinking: list[bool] = []  # что сообщили через use_thinking

    def use_thinking(self, supported: bool) -> None:
        self.thinking.append(supported)

    async def warm_up(self) -> None:
        if self.warm_gate is not None:
            await self.warm_gate.wait()
        if self.warm_error is not None:
            raise self.warm_error
        self.warmed += 1

    async def unload(self, timeout_s: float = 1.0) -> None:
        self.unloaded.append(timeout_s)

    def models(self) -> frozenset[str]:
        return frozenset({self.model})

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        if self.model in set(names):
            await self.unload(timeout_s)
