"""Тесты сети исполнителей: глубина передачи, циклы и вариант без правила передачи."""

from network_helpers import (
    BIG,
    CODER,
    DISPATCHER,
    call,
    collect,
    handoffs,
    member,
    texts,
)

from fakes.fake_executor import FakeExecutor
from smartesp.network import ExecutorNetwork


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


async def test_member_at_max_depth_answers_with_plain_variant() -> None:
    a = FakeExecutor([call("big", "задача B")])
    b = FakeExecutor([call("coder", "задача C")])
    c = FakeExecutor([call("dispatcher", "задача D")])
    c_plain = FakeExecutor(["Ответ C без правила."])
    members = {
        "dispatcher": member(a, "Диспетчер", [BIG]),
        "big": member(b, "Большая модель", [CODER]),
        "coder": member(c, "Программист", [DISPATCHER], plain=c_plain),
    }
    parts = await collect(ExecutorNetwork("dispatcher", members))
    assert texts(parts) == ["Ответ C без правила."]
    assert c.calls == []  # вариант с правилом передачи на этой глубине не спрашивается
    assert c_plain.tools == [()]


async def test_member_below_max_depth_answers_with_rule_variant() -> None:
    entry = FakeExecutor([call("big", "задача B")])
    big = FakeExecutor(["Ответ B."])
    big_plain = FakeExecutor(["Не то."])
    members = {
        "dispatcher": member(entry, "Диспетчер", [BIG]),
        "big": member(big, "Большая модель", [CODER], plain=big_plain),
        "coder": member(FakeExecutor([]), "Программист"),
    }
    parts = await collect(ExecutorNetwork("dispatcher", members))
    assert texts(parts) == ["Ответ B."]
    assert big_plain.calls == []
