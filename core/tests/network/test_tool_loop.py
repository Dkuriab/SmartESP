"""Тесты вызова инструментов коннекторов в сети исполнителей."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from network_helpers import BIG, QUESTION, call, collect, handoffs, texts

from fakes.fake_executor import FakeOllama
from fakes.fake_toolbox import FakeToolBox, tool_spec
from smartesp.contracts import ChatMessage, Executor, ReplyPart, ToolCall, ToolResult, ToolSpec
from smartesp.network import ExecutorNetwork, Member, MemberSpec, build_network

NOTE = tool_spec("note_add")
LIST = tool_spec("note_list")
FAILURE = ReplyPart("Не получилось выполнить действие.", failure=True)
BREAK = ReplyPart("\n")  # граница предложения перед вызовом


class ScriptedExecutor:
    """Модель по сценарию: n-й вызов run отдаёт n-й ответ (после конца — последний)."""

    def __init__(self, *turns: Sequence[str | ReplyPart]) -> None:
        self.turns = turns
        self.calls: list[list[ChatMessage]] = []
        self.tools: list[tuple[ToolSpec, ...]] = []

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(list(messages))
        self.tools.append(tuple(tools))
        for part in self.turns[min(len(self.calls), len(self.turns)) - 1]:
            await asyncio.sleep(0)
            yield part if isinstance(part, ReplyPart) else ReplyPart(part)


def tool(name: str = "note_add", **arguments: object) -> ReplyPart:
    return ReplyPart(tool_call=ToolCall(name, dict(arguments)))


def net(
    entry: Executor, big: Executor | None = None, box: FakeToolBox | None = None, *, tools_ok: bool = True
) -> ExecutorNetwork:
    """Сеть: диспетчер (с целью big, если она есть) и big; инструменты ящика — у умеющих."""
    box = box or FakeToolBox([NOTE, LIST])
    specs = tuple(box.specs())
    targets = (BIG,) if big else ()
    members = {"dispatcher": Member(entry, "Диспетчер", targets, tools_ok, tools=specs if tools_ok else ())}
    if big is not None:
        members["big"] = Member(big, "Большая модель", (), True, tools=specs)
    return ExecutorNetwork("dispatcher", members, toolbox=box)


async def test_tool_result_goes_to_messages_and_answer_after_call_is_spoken() -> None:
    entry = ScriptedExecutor(["Записываю.", tool(text="молоко")], ["Записал."])
    box = FakeToolBox([NOTE], {"note_add": ToolResult("Записано: молоко")})
    parts = await collect(net(entry, box=box))
    assert parts == [ReplyPart("Записываю."), BREAK, ReplyPart("Записал.")]
    assert box.calls == [("note_add", {"text": "молоко"}, None)]
    assert entry.calls[1] == [
        *QUESTION,
        ChatMessage("assistant", "Записываю.", tool_calls=(ToolCall("note_add", {"text": "молоко"}),)),
        ChatMessage("tool", "Записано: молоко", tool_name="note_add"),
    ]
    assert entry.tools[1] == entry.tools[0] == (NOTE,)


async def test_text_before_call_is_given_before_the_call() -> None:
    box = FakeToolBox([NOTE])
    entry = ScriptedExecutor(["Записываю.", tool()], ["Записал."])
    stream = net(entry, box=box).run(QUESTION)
    assert await anext(stream) == ReplyPart("Записываю.")
    assert await anext(stream) == BREAK and box.calls == []  # граница — до вызова
    assert [p async for p in stream] == [ReplyPart("Записал.")]
    assert len(box.calls) == 1


async def test_two_calls_in_a_row() -> None:
    entry = ScriptedExecutor([tool("note_list")], ["Сейчас", tool(text="хлеб")], ["Готово."])
    box = FakeToolBox([NOTE, LIST])
    parts = await collect(net(entry, box=box))
    assert texts(parts) == ["Сейчас", "\n", "Готово."]
    assert [name for name, _, _ in box.calls] == ["note_list", "note_add"]
    assert entry.calls[2][1:] == [
        ChatMessage("assistant", "", tool_calls=(ToolCall("note_list", {}),)),
        ChatMessage("tool", "note_list: готово", tool_name="note_list"),
        ChatMessage("assistant", "Сейчас", tool_calls=(ToolCall("note_add", {"text": "хлеб"}),)),
        ChatMessage("tool", "note_add: готово", tool_name="note_add"),
    ]


async def test_no_break_without_text_or_after_line_end() -> None:
    entry = ScriptedExecutor(["Записываю.\n", tool(), tool("note_list")], ["Готово."])
    parts = await collect(net(entry))
    assert parts == [ReplyPart("Записываю.\n"), ReplyPart("Готово.")]


async def test_two_calls_in_one_answer() -> None:
    entry = ScriptedExecutor([tool("note_list"), tool()], ["Готово."])
    box = FakeToolBox([NOTE, LIST])
    parts = await collect(net(entry, box=box))
    assert parts == [ReplyPart("Готово.")]
    assert [name for name, _, _ in box.calls] == ["note_list", "note_add"]
    assert [m.role for m in entry.calls[1]] == ["user", "assistant", "tool", "assistant", "tool"]


async def test_fifth_call_gives_failure_and_ends_answer() -> None:
    entry = ScriptedExecutor(["Пробую.", tool()])
    box = FakeToolBox([NOTE])
    parts = await collect(net(entry, box=box))
    assert len(box.calls) == 4 and len(entry.calls) == 5
    assert parts == [*[ReplyPart("Пробую."), BREAK] * 4, ReplyPart("Пробую."), FAILURE]


async def test_unknown_tool_gives_error_result_to_model() -> None:
    entry = ScriptedExecutor([tool("rm_rf")], ["Не умею."])
    box = FakeToolBox([NOTE])
    parts = await collect(net(entry, box=box))
    assert parts == [ReplyPart("Не умею.")] and box.calls == []
    assert entry.calls[1][-1] == ChatMessage("tool", "Нет такого инструмента: rm_rf", tool_name="rm_rf")


async def test_tool_error_is_given_to_model() -> None:
    entry = ScriptedExecutor([tool()], ["Заметки сейчас недоступны."])
    box = FakeToolBox([NOTE], {"note_add": ToolResult("Коннектор не отвечает", is_error=True)})
    parts = await collect(net(entry, box=box))
    assert parts == [ReplyPart("Заметки сейчас недоступны.")]
    assert entry.calls[1][-1] == ChatMessage("tool", "Коннектор не отвечает", tool_name="note_add")


async def test_delegate_and_tool_in_one_answer() -> None:
    entry = ScriptedExecutor(["Записываю и спрошу.", tool(text="молоко"), call()])
    big = ScriptedExecutor(["4913."])
    box = FakeToolBox([NOTE])
    parts = await collect(net(entry, big, box))
    assert texts(parts) == ["Записываю и спрошу.", "\n", "4913."]
    assert [h.target for h in handoffs(parts)] == ["big"]
    assert len(box.calls) == 1 and len(entry.calls) == 1


async def test_entry_gets_toolbox_tools_with_delegate() -> None:
    entry = ScriptedExecutor(["Привет."])
    await collect(net(entry, ScriptedExecutor([]), FakeToolBox([NOTE])))
    assert [t.name for t in entry.tools[0]] == ["note_add", "delegate"]


async def test_target_calls_tools_too() -> None:
    entry = ScriptedExecutor([call()])
    big = ScriptedExecutor([tool(text="молоко")], ["Записала."])
    box = FakeToolBox([NOTE])
    parts = await collect(net(entry, big, box))
    assert texts(parts) == ["Записала."] and len(box.calls) == 1
    assert big.tools[0] == (NOTE,)
    assert big.calls[1][-1] == ChatMessage("tool", "note_add: готово", tool_name="note_add")


async def test_member_without_tools_gets_none() -> None:
    entry = ScriptedExecutor(["Привет."])
    await collect(net(entry, tools_ok=False))
    assert entry.tools == [()]


async def test_caller_tools_pass_through() -> None:
    lamp = tool_spec("lamp")
    entry = ScriptedExecutor(["Включаю.", tool("lamp")])
    box = FakeToolBox([NOTE])
    parts = [p async for p in net(entry, box=box).run(QUESTION, [lamp])]
    assert parts == [ReplyPart("Включаю."), tool("lamp")] and box.calls == []


SPECS = [
    MemberSpec("dispatcher", "Диспетчер", "", "small", "Промпт.", (("big", "сложное"),)),
    MemberSpec("big", "Большая модель", "", "big", "Промпт big."),
]


async def _capabilities(model: str) -> frozenset[str]:
    return frozenset({"completion"}) if model == "big" else frozenset({"completion", "tools"})


async def test_build_gives_toolbox_snapshot_only_to_tool_models() -> None:
    made: dict[str, FakeOllama] = {}

    def make(member_id: str, prompt: str) -> Executor:
        return made.setdefault(member_id, FakeOllama(["Привет."], prompt=prompt))

    box = FakeToolBox([NOTE])
    network = await build_network("dispatcher", SPECS, [], make, _capabilities, toolbox=box)
    box.tools.append(LIST)  # снимок на момент сборки: новый инструмент сеть не видит
    assert network.members["dispatcher"].tools == (NOTE,)
    assert network.members["big"].tools == ()
    await collect(network)
    assert [t.name for t in made["dispatcher"].tools[0]] == ["note_add", "delegate"]


async def test_build_without_toolbox_gives_no_tools() -> None:
    network = await build_network(
        "dispatcher", SPECS, [], lambda i, p: FakeOllama([], prompt=p), _capabilities
    )
    assert network.members["dispatcher"].tools == ()
