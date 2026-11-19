"""Тесты наблюдателя вызовов инструментов: сеть сообщает, кто какой инструмент вызвал и чем кончилось."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence

from network_helpers import BIG, QUESTION, call, collect

from fakes.fake_toolbox import FakeToolBox, tool_spec
from smartesp.contracts import ChatMessage, Executor, ReplyPart, ToolCall, ToolResult, ToolSpec, ToolUse
from smartesp.network import ExecutorNetwork, Member, MemberSpec, build_network

NOTE = tool_spec("note_add")


class Scripted:
    """Модель по сценарию: n-й вызов run отдаёт n-й ответ (после конца — последний)."""

    def __init__(self, *turns: Sequence[str | ReplyPart]) -> None:
        self.turns = turns
        self.calls = 0

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls += 1
        for part in self.turns[min(self.calls, len(self.turns)) - 1]:
            await asyncio.sleep(0)
            yield part if isinstance(part, ReplyPart) else ReplyPart(part)


def tool(name: str = "note_add") -> ReplyPart:
    return ReplyPart(tool_call=ToolCall(name, {}))


def net(entry: Executor, big: Executor | None, box: FakeToolBox, seen: list[ToolUse]) -> ExecutorNetwork:
    members = {"dispatcher": Member(entry, "Диспетчер", (BIG,) if big else (), True, tools=(NOTE,))}
    if big is not None:
        members["big"] = Member(big, "Большая модель", (), True, tools=(NOTE,))
    return ExecutorNetwork("dispatcher", members, toolbox=box, on_tool=seen.append)


async def test_call_is_reported_started_then_finished_ok() -> None:
    seen: list[ToolUse] = []
    await collect(net(Scripted([tool()], ["Записал."]), None, FakeToolBox([NOTE]), seen))
    assert seen == [
        ToolUse("dispatcher", "note_add", "started"),
        ToolUse("dispatcher", "note_add", "finished", ok=True),
    ]


async def test_failed_call_is_reported_not_ok() -> None:
    seen: list[ToolUse] = []
    box = FakeToolBox([NOTE], {"note_add": ToolResult("Не отвечает", is_error=True)})
    await collect(net(Scripted([tool()], ["Не вышло."]), None, box, seen))
    assert seen[-1] == ToolUse("dispatcher", "note_add", "finished", ok=False)


async def test_unknown_tool_is_not_reported() -> None:
    seen: list[ToolUse] = []
    await collect(net(Scripted([tool("rm_rf")], ["Не умею."]), None, FakeToolBox([NOTE]), seen))
    assert seen == []


async def test_target_call_is_reported_with_its_id() -> None:
    seen: list[ToolUse] = []
    await collect(net(Scripted([call()]), Scripted([tool()], ["Записала."]), FakeToolBox([NOTE]), seen))
    assert {use.executor for use in seen} == {"big"}


class SlowBox(FakeToolBox):
    """Ящик, чей вызов не кончается сам."""

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        await asyncio.Event().wait()
        raise AssertionError("недостижимо")


async def test_closed_stream_still_reports_finished() -> None:
    seen: list[ToolUse] = []
    stream = net(Scripted([tool()]), None, SlowBox([NOTE]), seen).run(QUESTION)
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.01)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()
    assert seen == [
        ToolUse("dispatcher", "note_add", "started"),
        ToolUse("dispatcher", "note_add", "finished", ok=False),
    ]


async def test_broken_observer_does_not_break_the_turn() -> None:
    def broken(use: ToolUse) -> None:
        raise RuntimeError("сломался")

    members = {"dispatcher": Member(Scripted([tool()], ["Записал."]), "Диспетчер", (), True, tools=(NOTE,))}
    network = ExecutorNetwork("dispatcher", members, toolbox=FakeToolBox([NOTE]), on_tool=broken)
    assert [p.text for p in await collect(network)] == ["Записал."]


async def _capabilities(model: str) -> frozenset[str]:
    return frozenset({"completion", "tools"})


async def test_build_passes_observer_to_network() -> None:
    seen: list[ToolUse] = []
    specs = [MemberSpec("dispatcher", "Диспетчер", "", "small", "Промпт.")]
    model = Scripted([tool()], ["Записал."])
    network = await build_network(
        "dispatcher", specs, [], lambda i, p: model, _capabilities, FakeToolBox([NOTE]), on_tool=seen.append
    )
    await collect(network)
    assert [use.state for use in seen] == ["started", "finished"]
