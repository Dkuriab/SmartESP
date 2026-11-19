"""Подделка проигрывания файлов для тестов HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator

from smartesp.contracts import PlaybackRefused


class FakeFilePlayback:
    def __init__(self) -> None:
        self.plays: list[tuple[str, bytes]] = []  # (колонка, весь файл)
        self.stops: list[str] = []
        self.error: PlaybackRefused | None = None  # бросается из play_file и stop_file
        self.stopped = True  # что вернёт stop_file

    async def play_file(self, device_id: str, source: AsyncIterator[bytes]) -> None:
        self.plays.append((device_id, b"".join([chunk async for chunk in source])))
        if self.error is not None:
            raise self.error

    async def stop_file(self, device_id: str) -> bool:
        self.stops.append(device_id)
        if self.error is not None:
            raise self.error
        return self.stopped
