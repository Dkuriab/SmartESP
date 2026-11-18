"""Общие подделки и запуск оркестратора для тестов разговора."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.contracts import Annotation, EventSink, Executor, SpeechToText, Utterance
from smartesp.conversation import History, Orchestrator

TIMEOUT = 2.0


def make_utterance(turn: int = 1, device_id: str = "kitchen") -> Utterance:
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
        executor: Executor | None,
        stt: SpeechToText | None = None,
        analyzer: RecordingAnalyzer | None = None,
        tts: CountingTTS | None = None,
        events: EventSink | None = None,
        **timing: float,
    ) -> None:
        self.port = FakeDevicePort(names={"kitchen": "Кухня"})
        self.tts = tts or CountingTTS()
        self.history = History(max_turns=10, max_age_s=600)
        self.analyzer = analyzer or RecordingAnalyzer()
        self.orchestrator = Orchestrator(
            self.port,
            stt or FakeSTT("Какая погода?"),
            self.analyzer,
            executor,
            self.tts,
            self.history,
            events=events,
            **timing,  # таймауты ожидания исполнителя (параметры Orchestrator)
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


async def wait_for(predicate: Callable[[], Awaitable[object]]) -> None:
    await asyncio.wait_for(predicate(), TIMEOUT)


async def until(condition: Callable[[], bool]) -> None:
    """Ждёт (не дольше TIMEOUT), пока условие станет истинным."""

    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), TIMEOUT)


class CountingSTT:
    """Распознавание: возвращает заданный текст и считает вызовы."""

    def __init__(self, text: str = "Какая погода?") -> None:
        self.calls = 0
        self._text = text

    async def transcribe(self, pcm: bytes) -> str:
        self.calls += 1
        return self._text
