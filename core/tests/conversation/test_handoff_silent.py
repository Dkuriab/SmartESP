"""Тесты оркестратора: передача без фразы — за диспетчера ничего не говорим, ожидание заполняет «думаю»."""

from collections.abc import AsyncIterator, Sequence

from conversation_helpers import Setup
from handoff_helpers import HANDOFF, PHRASE, TASK, THINKING, FakeNetwork, run_turn

from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, Handoff, ReplyPart, ToolCall, ToolSpec


async def test_silent_call_speaks_only_the_answer_and_thinks_at_once() -> None:
    network = FakeNetwork([], ["Ответ большой модели."], delay=0.25)
    sink = RecordingSink()
    setup = Setup(network, events=sink, thinking_interval_s=0.1, delegate_limit_s=5)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == ["Ответ большой модели."]  # без «Минутку, сейчас узнаю»
    assert setup.port.tones[:2] == [THINKING, THINKING]  # «думаю» сразу при передаче и в 0,1 с
    assert finished["status"] == "ok"
    assert finished["answer"] == "Ответ большой модели."
    assert setup.history.messages() == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("delegate", {"executor": "big", "task": TASK}),)),
        ChatMessage("tool", "Ответ большой модели.", tool_name="delegate"),
    ]


async def test_phrase_before_call_is_kept() -> None:
    sink = RecordingSink()
    setup = Setup(FakeNetwork([PHRASE], ["Ответ."]), events=sink)
    await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Ответ."]


async def test_nested_silent_calls_speak_only_the_result() -> None:
    class Nested(FakeNetwork):
        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            yield ReplyPart(handoff=HANDOFF)
            yield ReplyPart(handoff=Handoff("big", "coder", "Программист", "t"))
            yield ReplyPart("Итог.")

    sink = RecordingSink()
    setup = Setup(Nested([], []), events=sink)
    await run_turn(setup, sink)
    assert setup.tts.texts == ["Итог."]
