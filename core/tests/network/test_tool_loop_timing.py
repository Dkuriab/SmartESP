"""Цикл инструментов во времени: keep-alive, озвучка сказанного до вызова, отмена, сбой ящика."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
from network_helpers import BIG, QUESTION, call, collect

from fakes.fake_toolbox import FakeToolBox, tool_spec
from smartesp.contracts import ChatMessage, ExecutorError, ReplyPart, ToolCall, ToolResult, ToolSpec
from smartesp.conversation.sentences import split_sentences
from smartesp.conversation.streams import next_part
from smartesp.network import ExecutorNetwork, Member, tool_loop

NOTE = tool_spec("note_add")
KEEPALIVE = ReplyPart("")
BREAK = ReplyPart("\n")
CALL = ReplyPart(tool_call=ToolCall("note_add", {"text": "молоко"}))


@pytest.fixture(autouse=True)
def fast_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_loop, "TOOL_KEEPALIVE_S", 0.01)
    monkeypatch.setattr(tool_loop, "TOOL_FOLLOWUP_KEEPALIVE_LIMIT_S", 0.05)


class SlowToolBox(FakeToolBox):
    """Инструмент думает delay секунд или до gate; error — бросает вопреки договору."""

    def __init__(
        self, delay: float = 0, gate: asyncio.Event | None = None, error: Exception | None = None
    ) -> None:
        super().__init__([NOTE])
        self.delay, self.gate, self.error = delay, gate, error
        self.cancelled = False

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        result = await super().call(name, arguments, person)
        try:
            await asyncio.sleep(self.delay)
            if self.gate is not None:
                await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.error is not None:
            raise self.error
        return result


class Model:
    """Модель: первый прогон — first, повторные — then; повторный молчит delay секунд до первого куска.

    hang — повторный прогон зависает навсегда; closed — поток прогона закрыли, не дочитав.
    """

    def __init__(
        self, first: Sequence[ReplyPart], then: Sequence[ReplyPart], delay: float = 0, *, hang: bool = False
    ) -> None:
        self.first, self.then, self.delay, self.hang = first, then, delay, hang
        self.calls: list[list[ChatMessage]] = []
        self.closed = False

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(list(messages))
        try:
            if len(self.calls) > 1:
                await asyncio.sleep(self.delay)
                if self.hang:
                    await asyncio.Event().wait()
            for part in self.first if len(self.calls) == 1 else self.then:
                yield part
        except (GeneratorExit, asyncio.CancelledError):
            self.closed = True
            raise


def net(model: Model, box: FakeToolBox, *, with_big: bool = False) -> ExecutorNetwork:
    """Сеть из одного входного с инструментом NOTE; with_big — ещё цель big (диспетчер может передать)."""
    entry = Member(model, "Диспетчер", (BIG,) if with_big else (), True, tools=(NOTE,))
    members = {"dispatcher": entry}
    if with_big:
        members["big"] = Member(Model([ReplyPart("4913.")], []), "Большая модель", (), True)
    return ExecutorNetwork("dispatcher", members, toolbox=box)


async def test_keepalive_while_slow_tool_runs() -> None:
    model = Model([ReplyPart("Записываю."), CALL], [ReplyPart("Записал.")])
    parts = await collect(net(model, SlowToolBox(delay=0.1)))
    assert parts[:2] == [ReplyPart("Записываю."), BREAK] and parts[-1] == ReplyPart("Записал.")
    assert parts[2:-1] and set(parts[2:-1]) == {KEEPALIVE}
    assert len(parts[2:-1]) >= 3


async def test_keepalive_while_follow_up_run_is_slow() -> None:
    model = Model([ReplyPart("Записываю."), CALL], [ReplyPart("Записал.")], delay=0.1)
    parts = await collect(net(model, SlowToolBox()))
    assert parts[-1] == ReplyPart("Записал.") and parts.count(KEEPALIVE) >= 3


async def test_no_keepalive_before_anything_was_given() -> None:
    model = Model([CALL], [ReplyPart("Готово.")], delay=0.05)
    parts = await collect(net(model, SlowToolBox(delay=0.05)))
    assert parts == [ReplyPart("Готово.")]


async def test_sentence_before_call_is_spoken_while_tool_runs() -> None:
    gate = asyncio.Event()
    box = SlowToolBox(gate=gate)
    model = Model([ReplyPart("Записываю молоко в список."), CALL], [ReplyPart("Записала молоко в список.")])
    sentences = split_sentences(net(model, box).run(QUESTION))
    # утверждение «Записываю» страховка честности отдаёт, как только инструмент начал работу
    assert await anext(sentences) == "Записываю молоко в список." and not gate.is_set()
    rest = asyncio.ensure_future(anext(sentences))
    await asyncio.sleep(0.05)
    assert box.calls and not rest.done()  # инструмент думает, фраза до него уже ушла
    gate.set()
    assert await rest == "Записала молоко в список."


async def test_closing_during_tool_cancels_it() -> None:
    box = SlowToolBox(gate=asyncio.Event())
    stream = net(Model([ReplyPart("Записываю."), CALL], []), box).run(QUESTION)
    assert [await anext(stream) for _ in range(3)] == [ReplyPart("Записываю."), BREAK, KEEPALIVE]
    await stream.aclose()  # type: ignore[attr-defined]
    assert box.cancelled


async def test_toolbox_crash_goes_to_model_as_error() -> None:
    model = Model([CALL], [ReplyPart("Не вышло.")])
    parts = await collect(net(model, SlowToolBox(error=RuntimeError("баг"))))
    assert parts == [ReplyPart("Не вышло.")]
    assert model.calls[1][-1] == ChatMessage("tool", "Инструмент note_add не сработал.", tool_name="note_add")


async def test_followup_keepalive_stops_so_conversation_catches_hung_model() -> None:
    model = Model([ReplyPart("Записываю."), CALL], [], hang=True)
    stream = net(model, SlowToolBox()).run(QUESTION)
    parts: list[ReplyPart] = []
    async with asyncio.timeout(2):
        with pytest.raises(ExecutorError):  # предел паузы разговора (0.1 с) срабатывает
            while (part := await next_part(stream, 0.1)) is not None:
                parts.append(part)
    assert parts[:2] == [ReplyPart("Записываю."), BREAK]
    assert set(parts[2:]) == {KEEPALIVE} and 1 <= len(parts[2:]) <= 6  # keep-alive только ~0.05 с
    assert model.closed


async def test_closing_during_followup_wait_cancels_it() -> None:
    model = Model([ReplyPart("Записываю."), CALL], [], hang=True)
    stream = net(model, SlowToolBox()).run(QUESTION)
    assert [await anext(stream) for _ in range(3)] == [ReplyPart("Записываю."), BREAK, KEEPALIVE]
    assert len(model.calls) == 2 and not model.closed  # ждём первый кусок повторного прогона
    await stream.aclose()  # type: ignore[attr-defined]
    assert model.closed


async def test_swallowed_invalid_delegate_does_not_start_keepalives() -> None:
    model = Model([call("nobody"), CALL], [ReplyPart("Готово.")], delay=0.05)
    parts = await collect(net(model, SlowToolBox(delay=0.05), with_big=True))
    assert parts == [ReplyPart("Готово.")]
