"""Поддельная система Mac: запоминает вызовы, ничего не трогает в ОС."""

import asyncio
from dataclasses import dataclass, field

from mac_media_mcp.system import MediaKey, PermissionDenied, Player, SystemFailure, SystemTimeout, Track


@dataclass
class FakeSystem:
    """Подделка MediaSystem; поля задают состояние, `denied` — кому отказано в разрешении."""

    volume: int | None = 40
    devices: list[str] = field(default_factory=lambda: ["Динамики MacBook Pro", "JBL Flip 5"])
    current_output: str | None = "Динамики MacBook Pro"
    running: list[Player] = field(default_factory=lambda: [])
    tracks: dict[str, Track] = field(default_factory=lambda: {})
    library: dict[str, Track] = field(default_factory=lambda: {})
    has_spotify: bool = False
    denied: set[str] = field(default_factory=lambda: set())
    failure: str = ""
    pressed: list[MediaKey] = field(default_factory=lambda: [])
    volume_calls: list[int] = field(default_factory=lambda: [])
    spotify_queries: list[str] = field(default_factory=lambda: [])
    # Задержка ответа по цели («Music», «volume»…): зависший вызов — большая задержка.
    delays: dict[str, float] = field(default_factory=lambda: {})
    # Цели, чей запуск AppleScript кончился своим таймаутом.
    timeouts: set[str] = field(default_factory=lambda: set())

    async def _check(self, target: str) -> None:
        await asyncio.sleep(self.delays.get(target, 0))
        if target in self.timeouts:
            raise SystemTimeout(target if target in ("Music", "Spotify") else None)  # type: ignore[arg-type]
        if target in self.denied:
            raise PermissionDenied(target)  # type: ignore[arg-type]
        if self.failure:
            raise SystemFailure(self.failure)

    async def press_media_key(self, key: MediaKey) -> None:
        await self._check("keys")
        self.pressed.append(key)

    async def get_volume(self) -> int | None:
        await self._check("volume")
        return self.volume

    async def set_volume(self, percent: int) -> None:
        await self._check("volume")
        self.volume_calls.append(percent)
        self.volume = percent

    async def output_devices(self) -> list[str]:
        await self._check("audio")
        return list(self.devices)

    async def default_output(self) -> str | None:
        await self._check("audio")
        return self.current_output

    async def set_default_output(self, name: str) -> None:
        await self._check("audio")
        assert name in self.devices
        self.current_output = name

    async def running_players(self) -> list[Player]:
        return list(self.running)

    async def now_playing(self, player: Player) -> Track | None:
        await self._check(player)
        return self.tracks.get(player)

    async def spotify_installed(self) -> bool:
        return self.has_spotify

    async def music_search_play(self, query: str) -> Track | None:
        await self._check("Music")
        track = self.library.get(query)
        if track is not None:
            self.tracks["Music"] = track
        return track

    async def spotify_search_play(self, query: str) -> None:
        await self._check("Spotify")
        self.spotify_queries.append(query)
