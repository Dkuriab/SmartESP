"""Тесты прослушивания после вопроса Кузи и метки хода по прослушиванию."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Sequence

import pytest
from conversation_helpers import TIMEOUT, RecordingAnalyzer, Setup, make_utterance, running, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.contracts import ChatMessage, Executor, ExecutorError, ReplyPart, ToolSpec
from smartesp.conversation import History, Orchestrator


async def finish_turn(setup: Setup, sink: RecordingSink, utterance_origin: str = "wake") -> dict[str, object]:
    """Проводит ход 1 до конца (вместе с прослушиванием) и возвращает данные turn_finished."""
    setup.port.feed(dataclasses.replace(make_utterance(), origin=utterance_origin))
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
        await setup.orchestrator.wait_turns(TIMEOUT)
    return next(data for kind, data in sink.events if kind == "turn_finished")


@pytest.mark.parametrize(
    ("answer", "listens"),
    [
        (["Хорошо. ", "Какой город?"], [("kitchen", 1)]),
        (["Какой город? "], [("kitchen", 1)]),
        (["Какой город?» "], [("kitchen", 1)]),  # закрывающая кавычка после знака
        (["**Какой город?**"], [("kitchen", 1)]),  # разметка снимается перед проверкой
        (["Какой город? Ладно, неважно."], []),  # вопрос не последний
        (["Готово."], []),
    ],
)
async def test_listen_after_question(answer: list[str], listens: list[tuple[str, int]]) -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(answer), events=sink)
    finished = await finish_turn(setup, sink)
    assert finished["status"] == "ok"
    assert setup.port.listen_afters == listens


async def test_no_listen_when_setting_off() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Какой город?"]), events=sink)
    setup.orchestrator.set_speech(True, False)
    await finish_turn(setup, sink)
    assert setup.port.listen_afters == []


async def test_no_listen_when_turn_interrupted() -> None:
    class Interrupting:
        def __init__(self, port: FakeDevicePort) -> None:
            self._port = port

        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            yield ReplyPart("Хорошо, договорились. ")
            await asyncio.sleep(0.01)
            self._port.deactivate("kitchen", 1)  # перебили словом посреди ответа
            yield ReplyPart("Какой город?")

    sink = RecordingSink()
    port = FakeDevicePort(names={"kitchen": "Кухня"})
    setup = Setup(Interrupting(port), events=sink, port=port)
    finished = await finish_turn(setup, sink)
    assert finished["status"] == "interrupted"
    assert setup.port.listen_afters == []


async def test_no_listen_when_turn_failed() -> None:
    sink = RecordingSink()
    executor = FakeExecutor(["Какой город?"], error=ExecutorError("упала"), error_after=1)
    setup = Setup(executor, events=sink)
    finished = await finish_turn(setup, sink)
    assert finished["status"] == "error"
    assert setup.port.listen_afters == []


async def test_listen_turn_origin() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Синий — хороший цвет."]), events=sink)
    finished = await finish_turn(setup, sink, "listen")
    assert finished["origin"] == "listen"
    assert finished["kind"] == "turn"


async def test_wake_turn_origin() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Солнечно."]), events=sink)
    finished = await finish_turn(setup, sink)
    assert finished["origin"] == "wake"


async def test_speech_uses_current_tts() -> None:
    setup = Setup(FakeExecutor([]))
    audio = [
        chunk async for chunk in setup.orchestrator.speech("Большая модель отвечает: Готово. Ещё фраза.")
    ]
    assert len(audio) >= 1
    assert setup.tts.texts == ["Большая модель отвечает: Готово.", "Ещё фраза."]


async def test_speech_without_tts_raises() -> None:
    executor: Executor = FakeExecutor([])
    orchestrator = Orchestrator(
        FakeDevicePort(), FakeSTT("x"), RecordingAnalyzer(), executor, None, History(10, 600)
    )
    with pytest.raises(RuntimeError):
        orchestrator.speech("Привет.")
