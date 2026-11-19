"""Подделка порта колонок: очередь реплик, запись проигранного звука, сигналов и ходов ядра."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from smartesp.contracts import Delivery, Utterance


@dataclass
class PlayCall:
    """Один вызов play: какой ход и сколько звука колонка успела забрать."""

    device_id: str
    turn: int
    audio: bytes
    finished: bool  # True — дошли до конца потока (настоящий хаб шлёт reply_end)


@dataclass
class AnnounceCall:
    """Один вызов announce: колонка, весь звук объявления и выданный итог."""

    device_id: str
    audio: bytes
    result: Delivery


class FakeDevicePort:
    def __init__(self, names: dict[str, str] | None = None) -> None:
        self.plays: list[PlayCall] = []
        self.tones: list[tuple[str, str]] = []
        self.inactive: set[tuple[str, int]] = set()  # ходы, ставшие неактуальными
        self.proactive: set[str] = set()  # колонки v3: подключены и умеют речь по инициативе
        self.busy: set[str] = set()  # колонки, на которых идёт ход (is_busy)
        self.deliveries: list[Delivery] = []  # итоги следующих announce по порядку; кончились — delivered
        self.announces: list[AnnounceCall] = []
        self.listens: list[str] = []  # колонки, которым ушёл listen
        self.listen_afters: list[tuple[str, int]] = []
        self.last_active: str | None = None  # что вернёт last_active_device
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

    async def wait_announces(self, count: int) -> None:
        """Ждёт, пока announce завершится count раз."""
        async with self._changed:
            await self._changed.wait_for(lambda: len(self.announces) >= count)

    def supports_proactive(self, device_id: str) -> bool:
        return device_id in self.proactive

    def is_busy(self, device_id: str) -> bool:
        return device_id in self.busy

    async def announce(self, device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        # Колонка не v3 — lost без звука, как у хаба; иначе забирает весь звук.
        # Источник звука упал — lost, как у хаба (ход потерян, колонке cancel_turn).
        received: list[bytes] = []
        broken = False
        try:
            if device_id in self.proactive:
                async for chunk in audio:
                    received.append(chunk)
        except Exception:
            broken = True
        finally:
            if isinstance(audio, AsyncGenerator):
                await audio.aclose()
        result: Delivery = "lost"
        if device_id in self.proactive and not broken:
            result = self.deliveries.pop(0) if self.deliveries else "delivered"
        self.announces.append(AnnounceCall(device_id, b"".join(received), result))
        async with self._changed:
            self._changed.notify_all()
        return result

    async def listen(self, device_id: str) -> bool:
        if device_id not in self.proactive:
            return False
        self.listens.append(device_id)
        return True

    async def listen_after(self, device_id: str, turn: int) -> None:
        self.listen_afters.append((device_id, turn))

    def last_active_device(self) -> str | None:
        return self.last_active

    def proactive_devices(self) -> list[str]:
        return sorted(self.proactive, key=lambda device_id: (self.device_name(device_id), device_id))
