"""Тесты оркестратора хода: поддельные колонка, STT, исполнитель и TTS."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.contracts import (
    Annotation,
    ChatMessage,
    Executor,
    ExecutorError,
    ReplyPart,
    SpeechToText,
    Utterance,
)
from smartesp.conversation import History, Orchestrator

TIMEOUT = 2.0


def _utterance(turn: int = 1, device_id: str = "kitchen") -> Utterance:
    return Utterance(device_id=device_id, turn=turn, pcm=b"\x00\x00" * 160, started_at=0.0)


class CountingTTS(FakeTTS):
    """FakeTTS, который считает вызовы synthesize."""

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        self.texts.append(text)
        return super().synthesize(text, style)


class RecordingAnalyzer:
    """Обработчики: запоминают реплику, возвращают заданные пометки."""

    def __init__(self, annotations: list[Annotation] | None = None) -> None:
        self.seen: list[Utterance] = []
        self._annotations = annotations or []

    async def __call__(self, utterance: Utterance) -> list[Annotation]:
        self.seen.append(utterance)
        return self._annotations


class Setup:
    def __init__(
        self,
        executor: Executor,
        stt: SpeechToText | None = None,
        analyzer: RecordingAnalyzer | None = None,
    ) -> None:
        self.port = FakeDevicePort(names={"kitchen": "Кухня"})
        self.tts = CountingTTS()
        self.history = History(max_turns=10, max_age_s=600)
        self.analyzer = analyzer or RecordingAnalyzer()
        self.orchestrator = Orchestrator(
            self.port, stt or FakeSTT("Какая погода?"), self.analyzer, executor, self.tts, self.history
        )


@asynccontextmanager
async def running(setup: Setup) -> AsyncIterator[None]:
    """Запускает orchestrator.run() на время блока и останавливает его."""
    task = asyncio.create_task(setup.orchestrator.run())
    try:
        yield
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def _wait(predicate: Callable[[], Awaitable[None]]) -> None:
    await asyncio.wait_for(predicate(), TIMEOUT)


async def test_happy_path() -> None:
    executor = FakeExecutor(["Сегодня солнечно и тепло. ", "Хорошего тебе дня!"])
    analyzer = RecordingAnalyzer([Annotation(text="говорит Даня", source="voice")])
    setup = Setup(executor, analyzer=analyzer)
    setup.port.feed(_utterance())
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert (play.device_id, play.turn, play.finished) == ("kitchen", 1, True)
    assert len(play.audio) > 0
    assert analyzer.seen[0].text == "Какая погода?"
    user = executor.calls[0][-1]
    assert user == ChatMessage("user", "[voice] говорит Даня\nКолонка: Кухня\n\nКакая погода?")
    assert setup.tts.texts == ["Сегодня солнечно и тепло.", "Хорошего тебе дня!"]
    assert setup.history.messages() == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", "Сегодня солнечно и тепло. Хорошего тебе дня!"),
    ]
    assert setup.port.tones == []


async def test_history_goes_to_next_question() -> None:
    executor = FakeExecutor(["Солнечно."])
    setup = Setup(executor)
    setup.port.feed(_utterance(1))
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
        setup.port.feed(_utterance(2))
        await _wait(lambda: setup.port.wait_plays(2))
    assert executor.calls[1][:2] == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", "Солнечно."),
    ]


async def test_meaningless_transcript_plays_empty_reply() -> None:
    executor = FakeExecutor(["Не должно прозвучать."])
    setup = Setup(executor, stt=FakeSTT("Субтитры сделал DimaTorzok"))
    setup.port.feed(_utterance())
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
    assert executor.calls == []
    assert setup.analyzer.seen == []
    assert setup.port.plays[0].audio == b""
    assert setup.port.plays[0].finished
    assert setup.history.messages() == []


async def test_executor_error_plays_error_tone() -> None:
    executor = FakeExecutor([], error=ExecutorError("нет ollama"))
    setup = Setup(executor)
    setup.port.feed(_utterance(1))
    setup.port.feed(_utterance(2))
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(2))
    assert setup.port.tones == [("kitchen", "error"), ("kitchen", "error")]
    assert [(p.turn, p.audio, p.finished) for p in setup.port.plays] == [(1, b"", True), (2, b"", True)]
    assert setup.tts.texts == []
    assert setup.history.messages() == []


class MidStreamFailingExecutor:
    """Отдаёт одно предложение и падает с ExecutorError."""

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        yield ReplyPart("Первое предложение ответа. ")
        raise ExecutorError("связь с ollama пропала")


async def test_executor_error_mid_reply_ends_reply_and_plays_tone() -> None:
    setup = Setup(MidStreamFailingExecutor())
    setup.port.feed(_utterance())
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
    assert setup.port.plays[0].finished
    assert len(setup.port.plays[0].audio) > 0
    assert setup.port.tones == [("kitchen", "error")]
    assert setup.history.messages() == []


class StoppingExecutor:
    """10 предложений с задержкой; после stop_after-го хаб объявляет ход неактуальным."""

    def __init__(self, port: FakeDevicePort, stop_after: int) -> None:
        self._port = port
        self._stop_after = stop_after
        self.read = 0
        self.closed = False

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
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
    setup.port.feed(_utterance())
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
    assert executor.read == 2
    assert executor.closed
    assert len(setup.tts.texts) <= 1
    assert not setup.port.plays[0].finished
    assert setup.history.messages() == []


async def test_inactive_after_stt_skips_executor() -> None:
    executor = FakeExecutor(["Не должно прозвучать."])
    setup = Setup(executor)
    setup.port.deactivate("kitchen", 1)
    setup.port.feed(_utterance(1))
    setup.port.feed(_utterance(2))
    async with running(setup):
        await _wait(lambda: setup.port.wait_plays(1))
    assert len(executor.calls) == 1  # только ход 2
    assert [p.turn for p in setup.port.plays] == [2]


async def test_failing_turn_is_logged_and_run_continues(caplog: pytest.LogCaptureFixture) -> None:
    class FlakySTT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, pcm: bytes) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("сломался распознаватель")
            return "Какая погода?"

    setup = Setup(FakeExecutor(["Солнечно."]), stt=FlakySTT())
    setup.port.feed(_utterance(1))
    setup.port.feed(_utterance(2))
    with caplog.at_level(logging.ERROR):
        async with running(setup):
            await _wait(lambda: setup.port.wait_plays(1))
    assert [p.turn for p in setup.port.plays] == [2]
    assert any("сломался распознаватель" in str(r.exc_info) for r in caplog.records)


async def test_turn_log_has_latencies(caplog: pytest.LogCaptureFixture) -> None:
    setup = Setup(FakeExecutor(["Солнечно и тепло."]))
    setup.port.feed(_utterance())
    with caplog.at_level(logging.INFO, logger="smartesp.conversation"):
        async with running(setup):
            await _wait(lambda: setup.port.wait_plays(1))
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
    setup.port.feed(_utterance())
    task = asyncio.create_task(setup.orchestrator.run())
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, TIMEOUT)
    assert setup.port.plays == []
