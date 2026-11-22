"""Человек хода: узнан по голосу или назван каналом API → лента (имя и id) и CALL_CONTEXT скиллам."""

from collections.abc import AsyncIterator, Sequence

from conversation_helpers import RecordingAnalyzer, Setup, make_utterance, running, until

from fakes.fake_events import RecordingSink
from smartesp.contracts import (
    CALL_CONTEXT,
    Annotation,
    CallContext,
    ChatMessage,
    Question,
    ReplyPart,
    ToolSpec,
)

SPEAKER = Annotation("Аня", "people", label="говорит", reference=True, person="Аня", person_id="a1b2c3d4")


class Watching:
    """Как сеть исполнителей: запоминает контекст хода, который увидел бы скилл, и отвечает."""

    def __init__(self) -> None:
        self.id = "dispatcher"
        self.seen: list[CallContext | None] = []

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.seen.append(CALL_CONTEXT.get())
        yield ReplyPart("Поставила.")


def _setup(network: Watching, sink: RecordingSink, notes: list[Annotation]) -> Setup:
    return Setup(network, analyzer=RecordingAnalyzer(notes), events=sink)  # type: ignore[arg-type]


def _finished(sink: RecordingSink) -> dict[str, object]:
    return next(data for kind, data in sink.events if kind == "turn_finished")


async def test_voice_turn_person_id_to_skills_name_to_feed() -> None:
    sink, network = RecordingSink(), Watching()
    setup = _setup(network, sink, [SPEAKER])
    setup.port.feed(make_utterance(4))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
    assert network.seen == [CallContext("a1b2c3d4", "kitchen", "Аня")]
    data = _finished(sink)
    assert (data["person"], data["person_id"]) == ("Аня", "a1b2c3d4")


async def test_unrecognized_voice_has_no_person() -> None:
    sink, network = RecordingSink(), Watching()
    setup = _setup(network, sink, [])
    setup.port.feed(make_utterance(5))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
    assert network.seen == [CallContext(None, "kitchen", "")]
    assert (_finished(sink)["person"], _finished(sink)["person_id"]) == ("", "")


async def test_api_channel_person_wins_over_voice() -> None:
    sink, network = RecordingSink(), Watching()
    setup = _setup(network, sink, [SPEAKER])
    question = Question(text="Поставь таймер", person="Боб", source="telegram", person_id="telegram:7")
    await setup.orchestrator.ask(question)
    assert network.seen == [CallContext("telegram:7", "", "Боб")]
    assert (_finished(sink)["person"], _finished(sink)["person_id"]) == ("Боб", "telegram:7")
