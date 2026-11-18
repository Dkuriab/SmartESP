"""Тесты оркестратора хода: ошибки исполнителя, STT, обработчиков и TTS — колонка не молчит."""

import logging
from collections.abc import AsyncIterator

import pytest
from conversation_helpers import (
    CountingTTS,
    RecordingAnalyzer,
    Setup,
    make_utterance,
    running,
    wait_for,
)

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.contracts import Annotation, ChatMessage, ExecutorError, ReplyPart, Utterance
from smartesp.conversation import Orchestrator


async def test_executor_error_plays_error_tone() -> None:
    executor = FakeExecutor([], error=ExecutorError("нет ollama"))
    setup = Setup(executor)
    setup.port.feed(make_utterance(1))
    setup.port.feed(make_utterance(2))
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(2))
    assert setup.port.tones == [("kitchen", "error"), ("kitchen", "error")]
    assert [(p.turn, p.audio, p.finished) for p in setup.port.plays] == [(1, b"", True), (2, b"", True)]
    assert setup.tts.texts == []
    assert setup.history.messages() == []


class MidStreamFailingExecutor:
    """Отдаёт одно предложение и падает с ExecutorError."""

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        yield ReplyPart("Первое предложение ответа. ")
        raise ExecutorError("связь с ollama пропала")


async def test_executor_error_mid_reply_ends_reply_without_tone() -> None:
    setup = Setup(MidStreamFailingExecutor())
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.plays[0].finished
    assert len(setup.port.plays[0].audio) > 0
    assert setup.port.tones == []  # оборванного ответа достаточно, сигнал ошибки не нужен
    assert setup.history.messages() == []


async def test_stt_failure_plays_error_tone_and_run_continues(caplog: pytest.LogCaptureFixture) -> None:
    class FlakySTT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, pcm: bytes) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("сломался распознаватель")
            return "Какая погода?"

    setup = Setup(FakeExecutor(["Солнечно."]), stt=FlakySTT())
    setup.port.feed(make_utterance(1))
    setup.port.feed(make_utterance(2))
    with caplog.at_level(logging.ERROR):
        async with running(setup):
            await wait_for(lambda: setup.port.wait_plays(2))
    # ход 1: сигнал ошибки и пустой ответ (колонка не ждёт молча), ход 2 — обычный
    assert setup.port.tones == [("kitchen", "error")]
    assert [(p.turn, p.finished) for p in setup.port.plays] == [(1, True), (2, True)]
    assert setup.port.plays[0].audio == b""
    assert len(setup.port.plays[1].audio) > 0
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Кухня" in r.getMessage() and "сломался распознаватель" in str(r.exc_info) for r in errors)


async def test_analyzer_failure_plays_error_tone() -> None:
    class BrokenAnalyzer(RecordingAnalyzer):
        async def __call__(self, utterance: Utterance) -> list[Annotation]:
            raise RuntimeError("обработчики сломались")

    executor = FakeExecutor(["Солнечно."])
    setup = Setup(executor, analyzer=BrokenAnalyzer())
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.tones == [("kitchen", "error")]
    assert (setup.port.plays[0].audio, setup.port.plays[0].finished) == (b"", True)
    assert executor.calls == []


class FailingTTS(CountingTTS):
    """Озвучивает первые good предложений, на следующем падает."""

    def __init__(self, good: int) -> None:
        super().__init__()
        self._good = good

    async def _broken(self) -> AsyncIterator[bytes]:
        raise RuntimeError("piper упал")
        yield b""

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        if len(self.texts) >= self._good:
            self.texts.append(text)
            return self._broken()
        return super().synthesize(text, style)


async def test_tts_failure_mid_reply_ends_reply_without_tone() -> None:
    executor = FakeExecutor(["Сегодня солнечно и тепло. ", "Хорошего тебе дня!"])
    setup = Setup(executor, tts=FailingTTS(good=1))
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert play.finished  # поток закончился штатно — настоящий хаб пошлёт reply_end
    assert len(play.audio) > 0
    assert setup.port.tones == []
    assert setup.history.messages() == []


async def test_tts_failure_before_any_audio_plays_tone() -> None:
    setup = Setup(FakeExecutor(["Сегодня солнечно и тепло."]), tts=FailingTTS(good=0))
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert (play.audio, play.finished) == (b"", True)
    assert setup.port.tones == [("kitchen", "error")]


@pytest.mark.parametrize("parts", [[], ["  ", "\n"]], ids=["no-parts", "whitespace"])
async def test_empty_answer_is_failure(parts: list[str], caplog: pytest.LogCaptureFixture) -> None:
    setup = Setup(FakeExecutor(parts))
    setup.port.feed(make_utterance())
    with caplog.at_level(logging.INFO, logger="smartesp.conversation"):
        async with running(setup):
            await wait_for(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert (play.audio, play.finished) == (b"", True)
    assert setup.port.tones == [("kitchen", "error")]
    assert setup.history.messages() == []
    assert "пустой ответ" in caplog.text
    assert "ход готов" not in caplog.text
    assert "ход ошибка" in caplog.text


class InterruptedFailingExecutor:
    """Пока ждали исполнителя, ход прервали, а потом исполнитель упал."""

    def __init__(self, port: FakeDevicePort) -> None:
        self._port = port

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        self._port.deactivate("kitchen", 1)
        raise ExecutorError("нет ollama")
        yield ReplyPart("")


async def test_no_error_tone_for_interrupted_turn() -> None:
    setup = Setup(FakeExecutor([]))
    setup.orchestrator = Orchestrator(
        setup.port,
        FakeSTT("Какая погода?"),
        setup.analyzer,
        InterruptedFailingExecutor(setup.port),
        setup.tts,
        setup.history,
    )
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.tones == []
