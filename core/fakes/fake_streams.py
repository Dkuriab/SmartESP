"""Подделки потоков: колонки для модуля streams (StreamLink) и сами потоки для HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from smartesp.contracts import (
    StreamAction,
    StreamCommand,
    StreamInfo,
    StreamItem,
    StreamListener,
    StreamRefused,
)


class FakeStreamLink:
    """Колонки: supported — умеющие потоки; sent — отправленные команды; online=False — не уходят."""

    def __init__(self, supported: Sequence[str] = ("d1",)) -> None:
        self.supported = set(supported)
        self.online = True
        self.sent: list[tuple[str, StreamCommand]] = []
        self.listener: StreamListener | None = None
        self.rates: dict[str, int] = {}  # частота потоков колонки; нет — 16000

    def supports_stream(self, device_id: str) -> bool:
        return device_id in self.supported

    def stream_rate(self, device_id: str) -> int:
        return self.rates.get(device_id, 16000)

    async def send_stream(self, device_id: str, command: StreamCommand) -> bool:
        if not self.online or device_id not in self.supported:
            return False
        self.sent.append((device_id, command))
        return True

    def use_stream_listener(self, listener: StreamListener) -> None:
        self.listener = listener

    def last(self) -> StreamCommand:
        return self.sent[-1][1]


class FakeSpeakerStreams:
    """Потоки для API: запоминает вызовы, error — бросается из всех действий."""

    def __init__(self) -> None:
        self.infos: list[StreamInfo] = [StreamInfo("d1", "Кухня", True)]
        self.calls: list[tuple[str, object]] = []
        self.error: StreamRefused | None = None
        self.audio: list[bytes] | None = None  # звук ссылки; None — ссылки нет
        self.input_list: list[str] = []  # устройства ввода Mac

    def status(self) -> list[StreamInfo]:
        return self.infos

    async def inputs(self) -> list[str]:
        return self.input_list

    def _answer(self, call: str, args: object) -> StreamInfo:
        self.calls.append((call, args))
        if self.error is not None:
            raise self.error
        return StreamInfo("d1", "Кухня", True, state="playing", title="Песня", count=1)

    async def play(
        self,
        device_id: str | None,
        items: Sequence[StreamItem],
        *,
        index: int = 0,
        start_s: float = 0.0,
        volume: float | None = None,
    ) -> StreamInfo:
        return self._answer("play", (device_id, list(items), index, start_s, volume))

    async def control(self, device_id: str | None, action: StreamAction) -> StreamInfo:
        return self._answer("control", (device_id, action))

    async def set_volume(
        self, device_id: str | None, *, volume: float | None = None, delta: float = 0.0
    ) -> StreamInfo:
        return self._answer("volume", (device_id, volume, delta))

    async def open(self, token: str) -> AsyncIterator[bytes] | None:
        self.calls.append(("open", token))
        if self.audio is None:
            return None
        return _iterate(self.audio)


async def _iterate(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk
