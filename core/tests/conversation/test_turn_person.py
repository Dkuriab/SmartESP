"""Человек хода: узнан по голосу (пометка с person) → лента и `_meta.person` вызовов инструментов."""

from collections.abc import AsyncIterator, Sequence

from conversation_helpers import RecordingAnalyzer, Setup, make_utterance, running, until

from fakes.fake_events import RecordingSink
from fakes.fake_toolbox import FakeToolBox
from smartesp.contracts import Annotation, ChatMessage, Question, ReplyPart, ToolBox, ToolSpec
from smartesp.conversation import current_person
from smartesp.tools import with_person

SPEAKER = Annotation("Аня", "people", label="говорит", reference=True, person="Аня")


class CallingTool:
    """Как сеть исполнителей: вызывает инструмент без человека (как ToolLoop), затем отвечает."""

    def __init__(self, toolbox: ToolBox) -> None:
        self.id = "dispatcher"
        self._toolbox = toolbox

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        await self._toolbox.call("timer_start", {"minutes": 5}, None)
        yield ReplyPart("Поставила.")


def _setup(box: FakeToolBox, sink: RecordingSink, notes: list[Annotation]) -> Setup:
    network = CallingTool(with_person(box, current_person))
    return Setup(network, analyzer=RecordingAnalyzer(notes), events=sink)  # type: ignore[arg-type]


def _finished(sink: RecordingSink) -> dict[str, object]:
    return next(data for kind, data in sink.events if kind == "turn_finished")


async def test_voice_turn_person_reaches_feed_and_tools() -> None:
    sink, box = RecordingSink(), FakeToolBox()
    setup = _setup(box, sink, [SPEAKER])
    setup.port.feed(make_utterance(4))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
    assert box.calls == [("timer_start", {"minutes": 5}, "Аня")]
    data = _finished(sink)
    assert data["person"] == "Аня" and data["annotations"] == [{"source": "people", "text": "Аня"}]


async def test_unrecognized_voice_calls_tools_without_person() -> None:
    sink, box = RecordingSink(), FakeToolBox()
    setup = _setup(box, sink, [])
    setup.port.feed(make_utterance(5))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
    assert box.calls == [("timer_start", {"minutes": 5}, None)] and _finished(sink)["person"] == ""


async def test_api_channel_person_wins_and_reaches_tools() -> None:
    sink, box = RecordingSink(), FakeToolBox()
    setup = _setup(box, sink, [SPEAKER])
    await setup.orchestrator.ask(Question(text="Поставь таймер", person="Боб", source="telegram"))
    assert box.calls == [("timer_start", {"minutes": 5}, "Боб")] and _finished(sink)["person"] == "Боб"


async def test_explicit_person_and_outside_turn() -> None:
    box = FakeToolBox()
    personal = with_person(box, current_person)
    await personal.call("t", {}, None)
    await personal.call("t", {}, "Даня")
    assert [call[2] for call in box.calls] == [None, "Даня"] and current_person() is None
    assert personal.specs() == []
