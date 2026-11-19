"""Тесты живой подсветки хода: executor_active, tool_call и вызовы инструментов в turn_finished."""

import asyncio
from collections.abc import AsyncIterator, Sequence

from conversation_helpers import Setup, make_utterance, running, until
from handoff_helpers import HANDOFF, PHRASE
from test_late_answer import GatedNetwork, late_setup

from fakes.fake_announcer import FakeAnnouncer
from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, ReplyPart, ToolObserver, ToolSpec, ToolUse
from smartesp.conversation import tool_observer


class Scripted:
    """Как сеть исполнителей с id: отдаёт куски; функция в сценарии — вызов наблюдателя."""

    def __init__(self, parts: Sequence[object]) -> None:
        self.id = "dispatcher"
        self._parts = parts

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        for part in self._parts:
            await asyncio.sleep(0)
            if callable(part):
                part()
            elif isinstance(part, ReplyPart):
                yield part
            else:
                yield ReplyPart(str(part))


async def run_turn(network: object, sink: RecordingSink) -> None:
    setup = Setup(network, events=sink)  # type: ignore[arg-type]
    setup.port.feed(make_utterance(7))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))


def active(sink: RecordingSink) -> list[tuple[object, object]]:
    return [(d["executor"], d["state"]) for k, d in sink.events if k == "executor_active"]


def kinds(sink: RecordingSink) -> list[str]:
    return [kind for kind, _ in sink.events]


async def test_entry_thinks_speaks_and_is_done_before_turn_finished() -> None:
    sink = RecordingSink()
    await run_turn(Scripted(["Сегодня ", "солнечно."]), sink)
    assert active(sink) == [("dispatcher", "thinking"), ("dispatcher", "speaking"), ("dispatcher", "done")]
    first = next(d for k, d in sink.events if k == "executor_active")
    assert first == {"turn_id": 7, "device_id": "kitchen", "executor": "dispatcher", "state": "thinking"}
    assert kinds(sink)[-2:] == ["executor_active", "turn_finished"]


async def test_handoff_moves_activity_to_target() -> None:
    sink = RecordingSink()
    await run_turn(Scripted([PHRASE, ReplyPart(handoff=HANDOFF), "", "Ответ."]), sink)
    assert active(sink) == [
        ("dispatcher", "thinking"),
        ("dispatcher", "speaking"),
        ("dispatcher", "done"),
        ("big", "thinking"),
        ("big", "speaking"),
        ("big", "done"),
    ]


async def test_failed_executor_is_done_too() -> None:
    sink = RecordingSink()
    await run_turn(Scripted([]), sink)
    assert active(sink) == [("dispatcher", "thinking"), ("dispatcher", "done")]


def calls(observe: ToolObserver, ok: bool = True) -> list[object]:
    return [
        lambda: observe(ToolUse("dispatcher", "calc_add", "started")),
        lambda: observe(ToolUse("dispatcher", "calc_add", "finished", ok=ok)),
    ]


async def test_tool_calls_become_events_and_go_to_turn_finished() -> None:
    sink = RecordingSink()
    observe = tool_observer(lambda name: "calc" if name == "calc_add" else "")
    await run_turn(Scripted([*calls(observe), "Четыре."]), sink)
    tool_events = [d for k, d in sink.events if k == "tool_call"]
    assert tool_events == [
        {
            "turn_id": 7,
            "device_id": "kitchen",
            "executor": "dispatcher",
            "connector": "calc",
            "tool": "calc_add",
            "state": "started",
            "ok": True,
        },
        {
            "turn_id": 7,
            "device_id": "kitchen",
            "executor": "dispatcher",
            "connector": "calc",
            "tool": "calc_add",
            "state": "finished",
            "ok": True,
        },
    ]
    finished = sink.events[-1][1]
    assert finished["tools"] == [
        {"executor": "dispatcher", "connector": "calc", "tool": "calc_add", "ok": True}
    ]


async def test_failed_tool_call_is_recorded_not_ok() -> None:
    sink = RecordingSink()
    observe = tool_observer(lambda name: "calc")
    await run_turn(Scripted([*calls(observe, ok=False), "Не вышло."]), sink)
    assert sink.events[-1][1]["tools"] == [
        {"executor": "dispatcher", "connector": "calc", "tool": "calc_add", "ok": False}
    ]


def test_observer_outside_a_turn_does_nothing() -> None:
    tool_observer(lambda name: "calc")(ToolUse("dispatcher", "calc_add", "started"))


async def test_deferred_target_is_done_only_when_its_answer_ends() -> None:
    network = GatedNetwork(["Готово."])
    setup, sink = late_setup(network)
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.port.feed(make_utterance())
    async with running(setup):
        await until(lambda: "turn_finished" in kinds(sink))
        assert active(sink)[-1] == ("big", "thinking")  # цель ещё думает в фоне
        network.release()
        await until(lambda: active(sink)[-1] == ("big", "done"))
    assert ("big", "speaking") in active(sink)
