"""Тесты оркестратора: подмена частей между ходами, «не готов», остановка приёма и drain."""

import asyncio
import time
from collections.abc import AsyncIterator

from conversation_helpers import (
    CountingSTT,
    CountingTTS,
    RecordingAnalyzer,
    Setup,
    make_utterance,
    running,
    until,
    wait_for,
)

from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, ReplyPart

ANSWER = "Первое предложение. Второе предложение."


class GatedExecutor:
    """Отдаёт первый кусок, ждёт разрешения и отдаёт второй."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        yield ReplyPart("Первое предложение. ")
        self.started.set()
        await self.gate.wait()
        yield ReplyPart("Второе предложение.")


class GatedSTT:
    """Распознавание, которое ждёт разрешения перед ответом."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def transcribe(self, pcm: bytes) -> str:
        self.entered.set()
        await self.gate.wait()
        return "Какая погода?"


class HangingExecutor:
    """Исполнитель, который молчит, пока его не отменят."""

    def __init__(self) -> None:
        self.called = False
        self.cancelled = False

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        self.called = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield ReplyPart("никогда")


def finished_statuses(sink: RecordingSink) -> list[object]:
    return [data["status"] for kind, data in sink.events if kind == "turn_finished"]


async def test_running_turn_keeps_old_tts() -> None:
    executor = GatedExecutor()
    setup = Setup(executor)
    old, new = setup.tts, CountingTTS()
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(executor.started.wait)
        setup.orchestrator.use_tts(new)
        executor.gate.set()
        await wait_for(lambda: setup.port.wait_plays(1))
        assert " ".join(old.texts) == ANSWER
        assert new.texts == []
        setup.port.feed(make_utterance(2))
        await wait_for(lambda: setup.port.wait_plays(2))
    assert " ".join(old.texts) == ANSWER
    assert " ".join(new.texts) == ANSWER


async def test_running_turn_keeps_old_executor() -> None:
    stt = GatedSTT()
    old, new = FakeExecutor(["Старый ответ."]), FakeExecutor(["Новый ответ."])
    setup = Setup(old, stt=stt)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(stt.entered.wait)
        setup.orchestrator.use_executor(new)
        stt.gate.set()
        await wait_for(lambda: setup.port.wait_plays(1))
        setup.port.feed(make_utterance(2))
        await wait_for(lambda: setup.port.wait_plays(2))
    assert len(old.calls) == 1
    assert len(new.calls) == 1
    assert setup.tts.texts == ["Старый ответ.", "Новый ответ."]


async def test_running_turn_keeps_old_stt_and_analyzer() -> None:
    stt = GatedSTT()
    setup = Setup(FakeExecutor(["Ответ."]), stt=stt)
    new_stt, new_analyzer = CountingSTT("Другой вопрос"), RecordingAnalyzer()
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(stt.entered.wait)
        setup.orchestrator.use_stt(new_stt)
        setup.orchestrator.use_analyzer(new_analyzer)
        stt.gate.set()
        await wait_for(lambda: setup.port.wait_plays(1))
        setup.port.feed(make_utterance(2))
        await wait_for(lambda: setup.port.wait_plays(2))
    assert new_stt.calls == 1
    assert [u.text for u in setup.analyzer.seen] == ["Какая погода?"]
    assert [u.text for u in new_analyzer.seen] == ["Другой вопрос"]


async def test_ready_requires_all_parts() -> None:
    assert Setup(FakeExecutor(["Ответ."])).orchestrator.ready
    setup = Setup(None)
    assert not setup.orchestrator.ready
    setup.orchestrator.use_executor(FakeExecutor(["Ответ."]))
    assert setup.orchestrator.ready


async def test_not_ready_turn_gets_error_tone() -> None:
    stt = CountingSTT()
    sink = RecordingSink()
    setup = Setup(None, stt=stt, events=sink)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
        await until(lambda: bool(finished_statuses(sink)))
    assert setup.port.tones == [("kitchen", "error")]
    assert [(p.turn, p.audio, p.finished) for p in setup.port.plays] == [(1, b"", True)]
    assert stt.calls == 0
    assert finished_statuses(sink) == ["error"]


async def test_stop_accepting_rejects_new_turns() -> None:
    stt = CountingSTT()
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Ответ."]), stt=stt, events=sink)
    setup.orchestrator.stop_accepting()
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
        await until(lambda: bool(finished_statuses(sink)))
    assert setup.port.tones == [("kitchen", "error")]
    assert [(p.turn, p.audio, p.finished) for p in setup.port.plays] == [(1, b"", True)]
    assert stt.calls == 0
    assert setup.tts.texts == []
    assert finished_statuses(sink) == ["error"]


async def test_drain_waits_for_short_turn() -> None:
    executor = FakeExecutor(["Ответ."], delay=0.2)
    setup = Setup(executor)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await until(lambda: bool(executor.calls))
        started = time.monotonic()
        await setup.orchestrator.drain(1.0)
        assert time.monotonic() - started < 0.9
        assert [(p.turn, p.finished) for p in setup.port.plays] == [(1, True)]
        assert len(setup.port.plays[0].audio) > 0


async def test_drain_cancels_hanging_turn() -> None:
    executor = HangingExecutor()
    sink = RecordingSink()
    setup = Setup(executor, events=sink)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await until(lambda: executor.called)
        started = time.monotonic()
        await setup.orchestrator.drain(0.1)
        elapsed = time.monotonic() - started
        assert 0.09 <= elapsed < 0.9
        assert executor.cancelled
        assert finished_statuses(sink) == ["interrupted"]


async def test_drain_without_turns_returns_at_once() -> None:
    setup = Setup(FakeExecutor(["Ответ."]))
    started = time.monotonic()
    await setup.orchestrator.drain(1.0)
    assert time.monotonic() - started < 0.1


async def test_wait_turns_waits_running_turn_without_cancelling() -> None:
    executor = FakeExecutor(["Ответ."], delay=0.2)
    setup = Setup(executor)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await until(lambda: bool(executor.calls))
        started = time.monotonic()
        await setup.orchestrator.wait_turns(1.0)
        assert time.monotonic() - started < 0.9
        assert [(p.turn, p.finished) for p in setup.port.plays] == [(1, True)]


async def test_wait_turns_gives_up_after_timeout_and_keeps_turn() -> None:
    executor = HangingExecutor()
    setup = Setup(executor)
    setup.port.feed(make_utterance(1))
    async with running(setup):
        await until(lambda: executor.called)
        await setup.orchestrator.wait_turns(0.05)
        assert not executor.cancelled
