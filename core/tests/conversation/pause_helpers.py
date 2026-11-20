"""Помощники тестов мягкого прерывания: колонка, берущая звук по команде, и синтез кусками."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from fakes.fake_device_port import FakeDevicePort, PlayCall
from fakes.fake_tts import FakeTTS

PIECES = 3  # кусков звука на предложение
PIECE = 64  # байт в куске


class PiecesTTS(FakeTTS):
    """Синтез: каждое предложение — PIECES кусков, первый байт куска — номер предложения (с 1)."""

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    async def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        self.texts.append(text)
        number = len(self.texts)
        for _ in range(PIECES):
            yield bytes([number]) * PIECE


class SequenceSTT:
    """Распознавание: тексты по очереди, последний повторяется."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)

    async def transcribe(self, pcm: bytes) -> str:
        return self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]


class SpeakingPort(FakeDevicePort):
    """Колонка: берёт звук ответа по куску, когда тест разрешит (step), и занята, пока ход идёт.

    Звук кончился (reply_end) — колонка «доигрывает» и ход заканчивается (playback_done).
    gated=False — звук берётся сразу.
    """

    def __init__(self) -> None:
        super().__init__({"kitchen": "Кухня"})
        self.proactive = {"kitchen"}
        self.gated = True
        self.taken: list[bytes] = []  # все взятые куски ответов по порядку
        self.speaking: set[tuple[str, int]] = set()
        self._steps = asyncio.Semaphore(0)
        self._finishing: set[asyncio.Task[None]] = set()

    def step(self, count: int = 1) -> None:
        """Разрешает колонке взять ещё count кусков."""
        for _ in range(count):
            self._steps.release()

    def is_busy(self, device_id: str) -> bool:
        return device_id in self.busy or any(d == device_id for d, _ in self.speaking)

    async def play(self, device_id: str, turn: int, audio: AsyncIterator[bytes]) -> None:
        self.speaking.add((device_id, turn))
        received: list[bytes] = []
        try:
            async for chunk in audio:
                received.append(chunk)
                self.taken.append(chunk)
                if self.gated:
                    await self._steps.acquire()
        finally:
            if isinstance(audio, AsyncGenerator):
                await audio.aclose()
        self.plays.append(PlayCall(device_id, turn, b"".join(received), True))
        self._finishing.add(asyncio.create_task(self._finish(device_id, turn)))

    async def _finish(self, device_id: str, turn: int) -> None:
        """Как колонка после reply_end: доигрывает отправленное и шлёт playback_done."""
        await asyncio.sleep(0.01)
        self.deactivate(device_id, turn)
        self.speaking.discard((device_id, turn))
        async with self._changed:
            self._changed.notify_all()


def sentences_of(audio: bytes) -> list[int]:
    """Номера предложений в звуке по порядку (без повторов подряд), и проверка, что они целые."""
    numbers = [audio[i] for i in range(0, len(audio), PIECE)]
    result: list[int] = []
    for number in numbers:
        if not result or result[-1] != number:
            result.append(number)
    for number in result:
        assert numbers.count(number) == PIECES, f"предложение {number} оборвано"
    return result
