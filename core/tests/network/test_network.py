"""Тесты сети исполнителей: передача задачи, глубина, ошибки, автопередача."""

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import (
    ChatMessage,
    Executor,
    ExecutorError,
    Handoff,
    ReplyPart,
    ToolCall,
    ToolSpec,
)
from smartesp.network import ExecutorNetwork, Member, Target

BIG = Target("big", "Большая модель", "сложные вопросы")
CODER = Target("coder", "Программист", "код")
DISPATCHER = Target("dispatcher", "Диспетчер", "простые вопросы")
QUESTION = [ChatMessage("user", "Сколько будет 17 в кубе?")]


def call(executor: str = "big", task: str = "Посчитать 17 в кубе", name: str = "delegate") -> ReplyPart:
    return ReplyPart(tool_call=ToolCall(name, {"executor": executor, "task": task}))


def member(executor: Executor, name: str, targets: Sequence[Target] = (), *, tools_ok: bool = True) -> Member:
    return Member(executor, name, tuple(targets), tools_ok)


def network(
    entry: FakeExecutor,
    big: FakeExecutor | None = None,
    *,
    targets: Sequence[Target] = (BIG,),
    tools_ok: bool = True,
) -> ExecutorNetwork:
    members = {"dispatcher": member(entry, "Диспетчер", targets, tools_ok=tools_ok)}
    if big is not None:
        members["big"] = member(big, "Большая модель")
    return ExecutorNetwork("dispatcher", members)


async def collect(net: ExecutorNetwork, messages: list[ChatMessage] = QUESTION) -> list[ReplyPart]:
    return [p async for p in net.run(messages)]


def handoffs(parts: list[ReplyPart]) -> list[Handoff]:
    return [p.handoff for p in parts if p.handoff is not None]


def texts(parts: list[ReplyPart]) -> list[str]:
    return [p.text for p in parts if p.text]


async def test_entry_without_call_streams_its_text() -> None:
    entry = FakeExecutor(["При", "вет."])
    parts = await collect(network(entry, FakeExecutor([])))
    assert texts(parts) == ["При", "вет."]
    assert handoffs(parts) == []


async def test_entry_gets_delegate_tool_with_its_targets() -> None:
    entry = FakeExecutor(["Привет."])
    await collect(network(entry, FakeExecutor([])))
    (tool,) = entry.tools[0]
    assert tool.name == "delegate"
    props = tool.parameters["properties"]
    assert isinstance(props, dict)
    assert props["executor"]["enum"] == ["big"]


async def test_phrase_then_call_gives_text_handoff_and_target_parts() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Четыре тысячи", " девятьсот тринадцать."])
    parts = await collect(network(entry, big))
    assert parts == [
        ReplyPart("Сейчас спрошу большую модель."),
        ReplyPart(handoff=Handoff("dispatcher", "big", "Большая модель", "Посчитать 17 в кубе")),
        ReplyPart("Четыре тысячи"),
        ReplyPart(" девятьсот тринадцать."),
    ]


async def test_target_gets_messages_with_task_appended() -> None:
    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Здравствуй"),
        ChatMessage("user", "Сколько будет 17 в кубе?"),
    ]
    big = FakeExecutor(["4913."])
    await collect(network(FakeExecutor([call()]), big), history)
    assert big.calls[0] == [
        *history[:2],
        ChatMessage("user", "Сколько будет 17 в кубе?\n\nЗадача от диспетчера: Посчитать 17 в кубе"),
    ]
    assert history[-1].content == "Сколько будет 17 в кубе?"


async def test_target_without_own_targets_gets_no_tools() -> None:
    big = FakeExecutor(["4913."])
    await collect(network(FakeExecutor([call()]), big))
    assert big.tools == [()]


def chain(max_depth: int = 2) -> tuple[FakeExecutor, FakeExecutor, FakeExecutor, ExecutorNetwork]:
    a = FakeExecutor([call("big", "задача B")])
    b = FakeExecutor([call("coder", "задача C")])
    c = FakeExecutor([call("dispatcher", "задача D"), "Ответ C."])
    members = {
        "dispatcher": member(a, "Диспетчер", [BIG]),
        "big": member(b, "Большая модель", [CODER]),
        "coder": member(c, "Программист", [DISPATCHER]),
    }
    return a, b, c, ExecutorNetwork("dispatcher", members, max_depth=max_depth)


async def test_depth_limits_tools_and_handoffs() -> None:
    a, b, c, net = chain()
    parts = await collect(net)
    assert [h.target for h in handoffs(parts)] == ["big", "coder"]
    assert texts(parts) == ["Ответ C."]
    assert [t.name for t in b.tools[0]] == ["delegate"]  # первая передача: у B инструмент есть
    assert c.tools == [()]  # вторая передача: у C инструмента нет
    assert len(a.calls) == 1


async def test_depth_one_leaves_first_target_without_tool() -> None:
    _, b, c, net = chain(max_depth=1)
    parts = await collect(net)
    assert [h.target for h in handoffs(parts)] == ["big"]
    assert b.tools == [()]
    assert c.calls == []


async def test_cycle_between_two_members_stops_at_depth_two() -> None:
    a = FakeExecutor([call("big", "туда")])
    b = FakeExecutor([call("dispatcher", "обратно")])
    members = {
        "dispatcher": member(a, "Диспетчер", [BIG]),
        "big": member(b, "Большая модель", [DISPATCHER]),
    }
    parts = await collect(ExecutorNetwork("dispatcher", members))
    assert [(h.source, h.target) for h in handoffs(parts)] == [("dispatcher", "big"), ("big", "dispatcher")]
    assert len(a.calls) == 2
    assert a.tools[1] == ()
    assert len(b.calls) == 1


@pytest.mark.parametrize("bad", [call("nobody"), call(task="  "), call(task="")])
async def test_bad_call_gives_no_handoff(bad: ReplyPart, caplog: pytest.LogCaptureFixture) -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", bad])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == []
    assert big.calls == []
    assert caplog.records and caplog.records[-1].levelname == "WARNING"


async def test_other_tool_call_passes_through() -> None:
    other = call(name="lamp")
    parts = await collect(network(FakeExecutor(["Включаю.", other]), FakeExecutor(["4913."])))
    assert parts == [ReplyPart("Включаю."), other]


async def test_call_with_non_string_arguments_is_ignored() -> None:
    bad = ReplyPart(tool_call=ToolCall("delegate", {"executor": 5, "task": None}))
    big = FakeExecutor(["4913."])
    parts = await collect(network(FakeExecutor([bad]), big))
    assert handoffs(parts) == []
    assert big.calls == []


async def test_valid_call_closes_source_right_away() -> None:
    entry = FakeExecutor(["Сейчас спрошу.", call(task="первая"), call(task="вторая"), "Лишний текст."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert [h.task for h in handoffs(parts)] == ["первая"]
    assert texts(parts) == ["Сейчас спрошу.", "4913."]
    assert parts[1].handoff is not None  # передача сразу после вызова
    assert entry.closed_early  # остаток ответа не читался
    assert len(big.calls) == 1


async def test_bad_call_before_valid_one_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    entry = FakeExecutor([call("nobody", "первая"), call(task="вторая")])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert [h.task for h in handoffs(parts)] == ["вторая"]
    assert any("nobody" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


async def test_target_error_becomes_failure_phrase() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Начало"], error=ExecutorError("нет модели"), error_after=1)
    parts = await collect(network(entry, big))
    assert parts[-1] == ReplyPart("Большая модель сейчас не отвечает.", failure=True)
    assert texts(parts) == [
        "Сейчас спрошу большую модель.",
        "Начало",
        "Большая модель сейчас не отвечает.",
    ]


async def test_entry_error_propagates() -> None:
    entry = FakeExecutor([], error=ExecutorError("Ollama недоступна"))
    with pytest.raises(ExecutorError):
        await collect(network(entry, FakeExecutor([])))


async def test_phrase_without_call_hands_off_automatically() -> None:
    entry = FakeExecutor(["Сейчас спрошу ", "большую модель."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == [
        Handoff("dispatcher", "big", "Большая модель", "Сколько будет 17 в кубе?", auto=True)
    ]
    assert texts(parts)[-1] == "4913."
    assert big.calls[0][-1].content.endswith("Задача от диспетчера: Сколько будет 17 в кубе?")


async def test_no_auto_handoff_after_bad_call() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call("nobody")])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == []


async def test_tools_not_ok_means_no_tool_and_no_auto_handoff() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big, tools_ok=False))
    assert entry.tools == [()]
    assert handoffs(parts) == []
    assert big.calls == []


async def test_tools_not_ok_drops_tools_passed_into_run() -> None:
    lamp = ToolSpec("lamp", "Включить свет.", {"type": "object", "properties": {}})
    entry = FakeExecutor(["Привет."])
    _ = [p async for p in network(entry, tools_ok=False).run(QUESTION, [lamp])]
    assert entry.tools == [()]


async def test_tools_passed_into_run_go_before_delegate() -> None:
    lamp = ToolSpec("lamp", "Включить свет.", {"type": "object", "properties": {}})
    entry = FakeExecutor(["Привет."])
    _ = [p async for p in network(entry, FakeExecutor([])).run(QUESTION, [lamp])]
    assert [t.name for t in entry.tools[0]] == ["lamp", "delegate"]


async def test_closing_mid_target_answer_closes_target_and_entry() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Первый.", "Второй.", "Третий."])
    stream = network(entry, big).run(QUESTION)
    seen: list[ReplyPart] = []
    async for part in stream:
        seen.append(part)
        if part.text == "Первый.":
            break
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()
    assert big.closed_early
    assert entry.closed_early  # поток входного закрыт сразу после вызова


async def test_cancel_while_target_waits_closes_target() -> None:
    entry = FakeExecutor([call()])
    big = FakeExecutor(["Долго."], delay=10)
    stream = network(entry, big).run(QUESTION)

    async def consume() -> None:
        async for _ in stream:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()
    assert big.closed_early
