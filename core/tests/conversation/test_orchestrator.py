"""Тесты оркестратора хода: обычный ответ, прерывание, журнал, остановка."""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

import pytest
from conversation_helpers import (
    TIMEOUT,
    RecordingAnalyzer,
    Setup,
    make_utterance,
    running,
    wait_for,
)

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.contracts import Annotation, ChatMessage, ReplyPart, ToolSpec
from smartesp.conversation import Orchestrator
from smartesp.conversation.prompt import CONTEXT_HEAD, REFERENCE_HEAD


async def test_happy_path() -> None:
    executor = FakeExecutor(["Сегодня солнечно и тепло. ", "Хорошего тебе дня!"])
    analyzer = RecordingAnalyzer([Annotation(text="говорит Даня", source="voice")])
    setup = Setup(executor, analyzer=analyzer)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert (play.device_id, play.turn, play.finished) == ("kitchen", 1, True)
    assert len(play.audio) > 0
    assert analyzer.seen[0].text == "Какая погода?"
    assert executor.calls[0][-3:] == [
        ChatMessage("system", f"{REFERENCE_HEAD} колонка — Кухня."),
        ChatMessage("system", f"{CONTEXT_HEAD}\n[voice] говорит Даня"),
        ChatMessage("user", "Какая погода?"),
    ]
    assert setup.tts.texts == ["Сегодня солнечно и тепло.", "Хорошего тебе дня!"]
    assert setup.history.messages() == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", "Сегодня солнечно и тепло. Хорошего тебе дня!"),
    ]
    assert setup.port.tones == []


async def test_history_goes_to_next_question() -> None:
    executor = FakeExecutor(["Солнечно."])
    setup = Setup(executor)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
        setup.port.feed(make_utterance(2))
        await wait_for(lambda: setup.port.wait_plays(2))
    assert executor.calls[1][:2] == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", "Солнечно."),
    ]


async def test_meaningless_transcript_plays_empty_reply() -> None:
    executor = FakeExecutor(["Не должно прозвучать."])
    setup = Setup(executor, stt=FakeSTT("Субтитры сделал DimaTorzok"))
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert executor.calls == []
    assert setup.analyzer.seen == []
    assert setup.port.plays[0].audio == b""
    assert setup.port.plays[0].finished
    assert setup.history.messages() == []


class StoppingExecutor:
    """10 предложений с задержкой; после stop_after-го хаб объявляет ход неактуальным."""

    def __init__(self, port: FakeDevicePort, stop_after: int) -> None:
        self._port = port
        self._stop_after = stop_after
        self.read = 0
        self.closed = False

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        try:
            for i in range(10):
                await asyncio.sleep(0.001)
                self.read += 1
                if self.read == self._stop_after:
                    self._port.deactivate("kitchen", 1)
                yield ReplyPart(f"Это предложение номер {i} в ответе. ")
        finally:
            self.closed = True


async def test_stops_when_turn_inactive() -> None:
    setup = Setup(FakeExecutor([]))
    executor = StoppingExecutor(setup.port, stop_after=2)
    setup.orchestrator = Orchestrator(
        setup.port, FakeSTT("Расскажи сказку"), setup.analyzer, executor, setup.tts, setup.history
    )
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert executor.read == 2
    assert executor.closed
    assert len(setup.tts.texts) <= 1
    assert not setup.port.plays[0].finished
    assert setup.history.messages() == []


async def test_inactive_after_stt_skips_executor() -> None:
    executor = FakeExecutor(["Не должно прозвучать."])
    setup = Setup(executor)
    setup.port.deactivate("kitchen", 1)
    setup.port.feed(make_utterance(1))
    setup.port.feed(make_utterance(2))
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert len(executor.calls) == 1  # только ход 2
    assert [p.turn for p in setup.port.plays] == [2]


async def test_turn_log_has_latencies(caplog: pytest.LogCaptureFixture) -> None:
    setup = Setup(FakeExecutor(["Солнечно и тепло."]))
    setup.port.feed(make_utterance())
    with caplog.at_level(logging.INFO, logger="smartesp.conversation"):
        async with running(setup):
            await wait_for(lambda: setup.port.wait_plays(1))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for needle in (
        "Кухня",
        "Какая погода?",
        "stt_ms=",
        "first_text_ms=",
        "first_audio_ms=",
        "Солнечно и тепло.",
    ):
        assert needle in text


async def test_stopping_run_cancels_turns() -> None:
    setup = Setup(FakeExecutor(["Долгий ответ."], delay=10))
    setup.port.feed(make_utterance())
    task = asyncio.create_task(setup.orchestrator.run())
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, TIMEOUT)
    assert setup.port.plays == []
