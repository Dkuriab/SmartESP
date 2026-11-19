"""Общее для тестов сети исполнителей: цели, вызовы delegate, сборка сети и сбор кусков."""

from collections.abc import Sequence

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, Executor, Handoff, ReplyPart, ToolCall
from smartesp.network import ExecutorNetwork, Member, Target

BIG = Target("big", "Большая модель", "сложные вопросы")
CODER = Target("coder", "Программист", "код")
DISPATCHER = Target("dispatcher", "Диспетчер", "простые вопросы")
QUESTION = [ChatMessage("user", "Сколько будет 17 в кубе?")]


def call(executor: str = "big", task: str = "Посчитать 17 в кубе", name: str = "delegate") -> ReplyPart:
    return ReplyPart(tool_call=ToolCall(name, {"executor": executor, "task": task}))


def member(
    executor: Executor,
    name: str,
    targets: Sequence[Target] = (),
    *,
    tools_ok: bool = True,
    plain: Executor | None = None,
) -> Member:
    return Member(executor, name, tuple(targets), tools_ok, plain)


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
