"""Общее для тестов передачи в ходе: подделка сети исполнителей, TTS со стилями, проведение хода.

Сеть подделана исполнителем, который отдаёт куски так же, как ExecutorNetwork:
фраза входного, ReplyPart(handoff=…), затем куски цели. Интервалы — доли секунды.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from conversation_helpers import CountingTTS, Setup, make_utterance, running, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, Handoff, ReplyPart, ToolSpec

THINKING = ("kitchen", "thinking")
PHRASE = "Сейчас спрошу большую модель."
TASK = "Объясни, почему небо голубое"
SILENT = "Большая модель сейчас не отвечает."
HANDOFF = Handoff("dispatcher", "big", "Большая модель", TASK)


class FakeNetwork:
    """Как сеть исполнителей: куски входного, передача, затем (после delay) куски цели."""

    def __init__(
        self,
        before: Sequence[str],
        target: Sequence[str | ReplyPart],
        *,
        delay: float = 0.0,
        port: FakeDevicePort | None = None,
    ) -> None:
        self.id = "dispatcher"
        self._before = before
        self._target = target
        self._delay = delay
        self._port = port  # задан — ход прерывается (barge-in), пока ждём цель
        self.tts: CountingTTS | None = None
        self.spoken_at_target: list[str] | None = None  # что уже прозвучало, когда спросили цель
        self.closed = False

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        try:
            for text in self._before:
                yield ReplyPart(text)
            yield ReplyPart(handoff=HANDOFF)
            if self.tts is not None:
                self.spoken_at_target = list(self.tts.texts)
            if self._port is not None:
                self._port.deactivate("kitchen", 1)
            await asyncio.sleep(self._delay)
            for part in self._target:
                yield part if isinstance(part, ReplyPart) else ReplyPart(part)
        finally:
            self.closed = True


class StyledTTS(CountingTTS):
    """CountingTTS со стилями normal и quiet, запоминает стиль каждого вызова."""

    def __init__(self) -> None:
        super().__init__()
        self.used: list[str] = []

    def styles(self) -> list[str]:
        return ["normal", "quiet"]

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        self.used.append(style)
        return super().synthesize(text, style)


async def run_turn(setup: Setup, sink: RecordingSink) -> dict[str, object]:
    """Проводит ход 1 и возвращает данные turn_finished."""
    setup.port.feed(make_utterance())
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
        await setup.port.wait_plays(1)
    return next(data for kind, data in sink.events if kind == "turn_finished")
