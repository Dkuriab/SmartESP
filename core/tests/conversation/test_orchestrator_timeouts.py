"""Тесты оркестратора: сигнал «думаю» и таймауты ожидания исполнителя.

Интервалы — доли секунды: моменты сигналов отсчитываются от начала ожидания,
поэтому их число не зависит от задержек цикла событий.
"""

import asyncio
from collections.abc import AsyncIterator

from conversation_helpers import Setup, make_utterance, running, wait_for

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, ReplyPart

THINKING = ("kitchen", "thinking")
ERROR = ("kitchen", "error")


async def test_thinking_tones_while_waiting_for_first_part() -> None:
    # первый кусок через 0,25 с: «думаю» в 0,1 и 0,2 с, следующий (0,3 с) уже не нужен
    setup = Setup(FakeExecutor(["Солнечно."], delay=0.25), thinking_interval_s=0.1, first_part_limit_s=5)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.tones == [THINKING, THINKING]
    play = setup.port.plays[0]
    assert play.finished and len(play.audio) > 0


async def test_gives_up_after_first_part_limit() -> None:
    # «думаю» в 0,05; 0,10; 0,15 с, в 0,175 с — сдаёмся: сигнал ошибки и пустой ответ
    setup = Setup(FakeExecutor(["Поздно."], delay=10), thinking_interval_s=0.05, first_part_limit_s=0.175)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.tones == [THINKING, THINKING, THINKING, ERROR]
    play = setup.port.plays[0]
    assert (play.audio, play.finished) == (b"", True)
    assert setup.tts.texts == []
    assert setup.history.messages() == []


class InterruptedSlowExecutor:
    """Ход прервали, а исполнитель всё думает."""

    def __init__(self) -> None:
        self.port: FakeDevicePort | None = None

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        assert self.port is not None
        self.port.deactivate("kitchen", 1)
        await asyncio.sleep(10)
        yield ReplyPart("Поздно.")


async def test_no_thinking_tone_for_inactive_turn() -> None:
    executor = InterruptedSlowExecutor()
    setup = Setup(executor, thinking_interval_s=0.05, first_part_limit_s=0.2)
    executor.port = setup.port
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert setup.port.tones == []


class StallingExecutor:
    """Отдаёт одно предложение и замолкает."""

    def __init__(self) -> None:
        self.closed = False

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        try:
            yield ReplyPart("Первое предложение ответа. ")
            await asyncio.sleep(10)
            yield ReplyPart("Не дождались.")
        finally:
            self.closed = True


async def test_idle_timeout_between_parts_ends_reply() -> None:
    executor = StallingExecutor()
    setup = Setup(executor, part_idle_s=0.1)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    play = setup.port.plays[0]
    assert play.finished  # поток закончился штатно — настоящий хаб пошлёт reply_end
    assert len(play.audio) > 0
    assert setup.tts.texts == ["Первое предложение ответа."]
    assert setup.port.tones == []  # звук уже был — сигнал ошибки не нужен
    assert executor.closed
    assert setup.history.messages() == []
