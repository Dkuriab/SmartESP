"""Поддельная система Mac: запоминает вызовы, ничего не трогает в ОС."""

from dataclasses import dataclass, field

from mac_media_mcp.system import MediaKey, PermissionDenied, Player, SystemFailure, Track


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

    def _check(self, target: str) -> None:
        if target in self.denied:
            raise PermissionDenied(target)  # type: ignore[arg-type]
        if self.failure:
            raise SystemFailure(self.failure)

    async def press_media_key(self, key: MediaKey) -> None:
        self._check("keys")
        self.pressed.append(key)

    async def get_volume(self) -> int | None:
        self._check("volume")
        return self.volume

    async def set_volume(self, percent: int) -> None:
        self._check("volume")
        self.volume_calls.append(percent)
        self.volume = percent

    async def output_devices(self) -> list[str]:
        self._check("audio")
        return list(self.devices)

    async def default_output(self) -> str | None:
        self._check("audio")
        return self.current_output

    async def set_default_output(self, name: str) -> None:
        self._check("audio")
        assert name in self.devices
        self.current_output = name

    async def running_players(self) -> list[Player]:
        return list(self.running)

    async def now_playing(self, player: Player) -> Track | None:
        self._check(player)
        return self.tracks.get(player)

    async def spotify_installed(self) -> bool:
        return self.has_spotify

    async def music_search_play(self, query: str) -> Track | None:
        self._check("Music")
        track = self.library.get(query)
        if track is not None:
            self.tracks["Music"] = track
        return track

    async def spotify_search_play(self, query: str) -> None:
        self._check("Spotify")
        self.spotify_queries.append(query)
