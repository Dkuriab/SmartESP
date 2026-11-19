"""Тесты оркестратора: молчаливый вызов передачи — фраза «Минутку, сейчас узнаю.» за диспетчера."""

from collections.abc import AsyncIterator, Sequence

from conversation_helpers import Setup
from handoff_helpers import CANNED, HANDOFF, PHRASE, TASK, THINKING, FakeNetwork, StyledTTS, run_turn

from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, Handoff, ReplyPart, ToolCall, ToolSpec


async def test_silent_call_speaks_canned_phrase_and_stores_it() -> None:
    network = FakeNetwork([], ["Ответ большой модели."], delay=0.25)
    sink = RecordingSink()
    setup = Setup(network, events=sink, thinking_interval_s=0.1, delegate_limit_s=5)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [CANNED, "Ответ большой модели."]
    assert setup.port.tones == [THINKING, THINKING]  # без немедленного «думаю»: в 0,1 и 0,2 с
    assert finished["status"] == "ok"
    assert finished["answer"] == f"{CANNED} Ответ большой модели."
    assert setup.history.messages() == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage(
            "assistant", CANNED, tool_calls=(ToolCall("delegate", {"executor": "big", "task": TASK}),)
        ),
        ChatMessage("tool", "Ответ большой модели.", tool_name="delegate"),
    ]


async def test_silent_call_after_style_tag_only_keeps_quiet() -> None:
    tts = StyledTTS()
    sink = RecordingSink()
    setup = Setup(FakeNetwork(["[style:quiet]"], ["Ответ."]), tts=tts, events=sink)
    finished = await run_turn(setup, sink)
    assert tts.texts[0] == CANNED
    assert tts.used[0] == "quiet"
    assert finished["answer"] == f"{CANNED} Ответ."


async def test_call_after_blank_text_counts_as_silent() -> None:
    sink = RecordingSink()
    setup = Setup(FakeNetwork(["  "], ["Ответ."]), events=sink)
    await run_turn(setup, sink)
    assert CANNED in setup.tts.texts


async def test_phrase_before_call_is_not_replaced() -> None:
    sink = RecordingSink()
    setup = Setup(FakeNetwork([PHRASE], ["Ответ."]), events=sink)
    await run_turn(setup, sink)
    assert CANNED not in setup.tts.texts


async def test_auto_handoff_gets_no_canned_phrase() -> None:
    class AutoNetwork(FakeNetwork):
        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            yield ReplyPart(PHRASE)
            yield ReplyPart(handoff=Handoff("dispatcher", "big", "Большая модель", TASK, auto=True))
            yield ReplyPart("Ответ.")

    sink = RecordingSink()
    setup = Setup(AutoNetwork([], []), events=sink)
    await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Ответ."]


async def test_second_silent_call_gets_no_canned_phrase() -> None:
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
    assert setup.tts.texts == [CANNED, "Итог."]


async def test_first_text_ms_is_canned_phrase_for_silent_call() -> None:
    # передача без фразы: за диспетчера звучит «Минутку…», это и есть первый текст
    network = FakeNetwork([], ["Ответ большой модели."], delay=0.2)
    sink = RecordingSink()
    finished = await run_turn(Setup(network, events=sink), sink)
    first_text_ms = finished["first_text_ms"]
    assert isinstance(first_text_ms, int) and first_text_ms < 100
