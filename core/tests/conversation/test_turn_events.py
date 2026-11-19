"""Тесты событий хода: turn_started, turn_heard, turn_finished."""

from conversation_helpers import RecordingAnalyzer, Setup, make_utterance, running, until

from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.contracts import Annotation, ExecutorError


def is_delay(value: object) -> bool:
    return isinstance(value, int | float) and value >= 0


async def run_turn(setup: Setup, sink: RecordingSink) -> None:
    setup.port.feed(make_utterance(7))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))


async def test_turn_events_sequence() -> None:
    sink = RecordingSink()
    analyzer = RecordingAnalyzer([Annotation(text="говорит Даня", source="voice")])
    setup = Setup(FakeExecutor(["Сегодня ", "солнечно."]), analyzer=analyzer, events=sink)
    await run_turn(setup, sink)
    assert [kind for kind, _ in sink.events] == ["turn_started", "turn_heard", "turn_finished"]
    started, heard, finished = (data for _, data in sink.events)
    assert started == {"turn_id": 7, "device_id": "kitchen", "device_name": "Кухня"}
    assert heard["turn_id"] == 7
    assert heard["text"] == "Какая погода?"
    assert is_delay(heard["stt_ms"])
    assert isinstance(finished["at"], float)
    assert {k: v for k, v in finished.items() if not k.endswith("_ms") and k != "at"} == {
        "turn_id": 7,
        "device_id": "kitchen",
        "device_name": "Кухня",
        "text": "Какая погода?",
        "annotations": [{"source": "voice", "text": "говорит Даня"}],
        "style": "normal",
        "answer": "Сегодня солнечно.",
        "status": "ok",
        "path": ["entry"],
        "delegations": [],
    }
    assert all(is_delay(finished[k]) for k in ("stt_ms", "first_text_ms", "first_audio_ms"))


async def test_turn_finished_error_on_executor_failure() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor([], error=ExecutorError("нет ollama")), events=sink)
    await run_turn(setup, sink)
    finished = sink.events[-1][1]
    assert sink.events[-1][0] == "turn_finished"
    assert finished["status"] == "error"
    assert finished["answer"] == ""
    assert finished["first_text_ms"] is None
    assert finished["first_audio_ms"] is None


async def test_turn_finished_meaningless() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Ответ."]), stt=FakeSTT("м"), events=sink)
    await run_turn(setup, sink)
    assert [kind for kind, _ in sink.events] == ["turn_started", "turn_heard", "turn_finished"]
    assert sink.events[-1][1]["status"] == "meaningless"
    assert sink.events[-1][1]["text"] == "м"


async def test_turn_finished_interrupted_when_turn_inactive() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Ответ."]), events=sink)
    setup.port.deactivate("kitchen", 7)
    await run_turn(setup, sink)
    assert sink.events[-1][1]["status"] == "interrupted"


async def test_works_without_event_sink() -> None:
    setup = Setup(FakeExecutor(["Ответ."]))
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await setup.port.wait_plays(1)
    assert setup.port.plays[0].finished
