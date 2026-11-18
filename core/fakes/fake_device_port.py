"""Подделка порта колонок: очередь реплик, запись проигранного звука и сигналов."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from smartesp.contracts import Utterance


@dataclass
class PlayCall:
    """Один вызов play: какой ход и сколько звука колонка успела забрать."""

    device_id: str
    turn: int
    audio: bytes
    finished: bool  # True — дошли до конца потока (настоящий хаб шлёт reply_end)


class FakeDevicePort:
    def __init__(self, names: dict[str, str] | None = None) -> None:
        self.plays: list[PlayCall] = []
        self.tones: list[tuple[str, str]] = []
        self.inactive: set[tuple[str, int]] = set()  # ходы, ставшие неактуальными
        self._names = names or {}
        self._utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self._changed = asyncio.Condition()

    def feed(self, utterance: Utterance) -> None:
        """Кладёт реплику, которую отдаст next_utterance."""
        self._utterances.put_nowait(utterance)

    def deactivate(self, device_id: str, turn: int) -> None:
        """Ход больше не актуален (barge-in, отмена, отключение)."""
        self.inactive.add((device_id, turn))

    async def wait_plays(self, count: int) -> None:
        """Ждёт, пока play завершится count раз."""
        async with self._changed:
            await self._changed.wait_for(lambda: len(self.plays) >= count)

    async def next_utterance(self) -> Utterance:
        return await self._utterances.get()

    def is_active(self, device_id: str, turn: int) -> bool:
        return (device_id, turn) not in self.inactive

    async def play(self, device_id: str, turn: int, audio: AsyncIterator[bytes]) -> None:
        # Как настоящий хаб: тянет звук, пока ход актуален, при раннем выходе закрывает поток.
        received: list[bytes] = []
        finished = False
        try:
            async for chunk in audio:
                if not self.is_active(device_id, turn):
                    break
                received.append(chunk)
            else:
                finished = self.is_active(device_id, turn)
        finally:
            if isinstance(audio, AsyncGenerator):
                await audio.aclose()
        self.plays.append(PlayCall(device_id, turn, b"".join(received), finished))
        async with self._changed:
            self._changed.notify_all()

    async def send_tone(self, device_id: str, name: str) -> None:
        self.tones.append((device_id, name))

    def device_name(self, device_id: str) -> str:
        return self._names.get(device_id, device_id)
