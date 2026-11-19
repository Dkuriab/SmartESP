"""Настоящая система Mac: реализация MediaSystem над osascript, CoreAudio и Quartz.

Блокирующие вызовы (CoreAudio, AppKit) идут в поток, чтобы не держать цикл.
"""

import asyncio
from collections.abc import Awaitable, Sequence
from typing import Any, Protocol
from urllib.parse import quote

from mac_media_mcp import coreaudio, keys, scripts
from mac_media_mcp.osascript import AppNotRunning, run_script
from mac_media_mcp.system import MediaKey, Player, SystemFailure, Track

_BUNDLES: dict[Player, str] = {"Music": "com.apple.Music", "Spotify": "com.spotify.client"}
_NOW_PLAYING: dict[Player, str] = {
    "Music": scripts.MUSIC_NOW_PLAYING,
    "Spotify": scripts.SPOTIFY_NOW_PLAYING,
}


class ScriptRunner(Protocol):
    """Запуск фиксированного AppleScript (как osascript.run_script)."""

    def __call__(self, script: str, args: Sequence[str] = (), *, app: Player | None = None) -> Awaitable[str]:
        """Выполняет script с аргументами args; app — для текста ошибки."""
        ...


def _workspace() -> Any:
    import AppKit  # pyright: ignore[reportMissingTypeStubs]

    appkit: Any = AppKit
    return appkit.NSWorkspace.sharedWorkspace()


def _running_bundles() -> set[str]:
    return {str(app.bundleIdentifier()) for app in _workspace().runningApplications()}


def _is_installed(bundle: str) -> bool:
    return _workspace().URLForApplicationWithBundleIdentifier_(bundle) is not None


class MacSystem:
    """MediaSystem на этом Mac; runner подменяется в тестах."""

    def __init__(self, runner: ScriptRunner = run_script) -> None:
        self._run = runner

    async def press_media_key(self, key: MediaKey) -> None:
        await asyncio.to_thread(lambda: keys.press(key))

    async def get_volume(self) -> int | None:
        return scripts.parse_volume(await self._run(scripts.VOLUME_GET))

    async def set_volume(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError(percent)
        await self._run(scripts.VOLUME_SET, [str(percent)])

    async def output_devices(self) -> list[str]:
        return list(await asyncio.to_thread(coreaudio.output_devices))

    async def default_output(self) -> str | None:
        devices = await asyncio.to_thread(coreaudio.output_devices)
        current = await asyncio.to_thread(coreaudio.default_output_id)
        return next((name for name, device in devices.items() if device == current), None)

    async def set_default_output(self, name: str) -> None:
        devices = await asyncio.to_thread(coreaudio.output_devices)
        device = devices.get(name)
        if device is None:
            raise SystemFailure(f"Устройство «{name}» пропало из списка.")
        await asyncio.to_thread(lambda: coreaudio.set_default_output_id(device))

    async def running_players(self) -> list[Player]:
        running = await asyncio.to_thread(_running_bundles)
        return [player for player, bundle in _BUNDLES.items() if bundle in running]

    async def now_playing(self, player: Player) -> Track | None:
        try:
            output = await self._run(_NOW_PLAYING[player], app=player)
        except AppNotRunning:
            return None  # плеер закрылся между проверкой и вопросом
        return scripts.parse_track(output)

    async def spotify_installed(self) -> bool:
        return await asyncio.to_thread(lambda: _is_installed(_BUNDLES["Spotify"]))

    async def music_search_play(self, query: str) -> Track | None:
        return scripts.parse_track(await self._run(scripts.MUSIC_SEARCH_PLAY, [query], app="Music"))

    async def spotify_search_play(self, query: str) -> None:
        await self._run(scripts.SPOTIFY_SEARCH_PLAY, [f"spotify:search:{quote(query)}"], app="Spotify")
