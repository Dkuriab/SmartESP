"""Слой над macOS без побочных эффектов: разбор ответов, ошибки osascript, вызовы MacSystem.

Настоящий osascript запускается только со скриптом, который не трогает ни одно
приложение (эхо аргумента), — громкость, клавиши и плееры не затрагиваются.
"""

import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from mac_media_mcp import keys, scripts
from mac_media_mcp.mac import MacSystem
from mac_media_mcp.osascript import run_script, script_error
from mac_media_mcp.system import PermissionDenied, Player, SystemFailure, Track

needs_osascript = pytest.mark.skipif(shutil.which("osascript") is None, reason="нужен macOS")


@dataclass
class FakeRunner:
    """Подделка запуска AppleScript: запоминает вызовы и отдаёт заготовленный ответ."""

    output: str = ""
    calls: list[tuple[str, tuple[str, ...], Player | None]] = field(default_factory=lambda: [])

    async def __call__(self, script: str, args: Sequence[str] = (), *, app: Player | None = None) -> str:
        self.calls.append((script, tuple(args), app))
        return self.output


# --- разбор ответов ---


def test_parse_volume() -> None:
    assert scripts.parse_volume("40\n") == 40
    assert scripts.parse_volume("missing value") is None
    assert scripts.parse_volume("") is None


def test_parse_track() -> None:
    assert scripts.parse_track("playing\nГруппа крови\nКино") == Track("Группа крови", "Кино", True)
    assert scripts.parse_track("paused\nПодкаст\nmissing value") == Track("Подкаст", "", False)
    assert scripts.parse_track("") is None
    assert scripts.parse_track("playing\n\n") is None


def test_scripts_have_no_placeholders() -> None:
    """Данные человека идут только через argv: в тексте скриптов нет подстановок."""
    for script in (scripts.VOLUME_SET, scripts.MUSIC_SEARCH_PLAY, scripts.SPOTIFY_SEARCH_PLAY):
        assert "argv" in script
        assert "{app}" not in script
    assert 'tell application "Music"' in scripts.MUSIC_NOW_PLAYING
    assert 'tell application "Spotify"' in scripts.SPOTIFY_NOW_PLAYING


# --- ошибки osascript ---


def test_permission_error_detected() -> None:
    error = script_error("execution error: Not authorized to send Apple events to Music. (-1743)", "Music")
    assert isinstance(error, PermissionDenied)
    assert error.target == "Music"


def test_other_script_errors() -> None:
    error = script_error("execution error: Music got an error: (-600)", "Music")
    assert isinstance(error, SystemFailure)
    assert "не запущено" in str(error)
    error = script_error("syntax error", "Spotify")
    assert str(error) == "Не получилось управлять приложением Spotify."
    assert isinstance(script_error("anything", None), SystemFailure)


@needs_osascript
async def test_run_script_passes_args_verbatim() -> None:
    tricky = 'кино" & (do shell script "echo взлом") & "\\'
    script = "on run argv\n\treturn item 1 of argv\nend run"
    assert await run_script(script, [tricky]) == tricky


@needs_osascript
async def test_run_script_error() -> None:
    with pytest.raises(SystemFailure):
        await run_script('error "boom" number -1')


@needs_osascript
async def test_run_script_timeout() -> None:
    with pytest.raises(SystemFailure, match="не отвечает"):
        await run_script("delay 5", app="Music", timeout_s=0.2)


# --- MacSystem с подделанным запуском ---


async def test_mac_volume_calls() -> None:
    runner = FakeRunner(output="35")
    system = MacSystem(runner)
    assert await system.get_volume() == 35
    await system.set_volume(70)
    assert runner.calls[-1] == (scripts.VOLUME_SET, ("70",), None)


async def test_mac_volume_rejects_out_of_range() -> None:
    runner = FakeRunner()
    with pytest.raises(ValueError):
        await MacSystem(runner).set_volume(101)
    assert runner.calls == []


async def test_mac_music_search_passes_query_as_argument() -> None:
    runner = FakeRunner(output="playing\nГруппа крови\nКино")
    track = await MacSystem(runner).music_search_play('Кино "Группа"')
    assert track == Track("Группа крови", "Кино")
    assert runner.calls == [(scripts.MUSIC_SEARCH_PLAY, ('Кино "Группа"',), "Music")]


async def test_mac_spotify_search_uri_encoded() -> None:
    runner = FakeRunner()
    await MacSystem(runner).spotify_search_play("the beatles")
    assert runner.calls == [(scripts.SPOTIFY_SEARCH_PLAY, ("spotify:search:the%20beatles",), "Spotify")]


async def test_mac_now_playing_uses_player_script() -> None:
    runner = FakeRunner(output="")
    assert await MacSystem(runner).now_playing("Spotify") is None
    assert runner.calls == [(scripts.SPOTIFY_NOW_PLAYING, (), "Spotify")]


# --- медиа-клавиши: только данные события ---


def test_media_key_event_data() -> None:
    assert keys.event_data("play_pause", down=True) == (0xA00, (16 << 16) | 0xA00)
    assert keys.event_data("next", down=False) == (0xB00, (19 << 16) | 0xB00)
    assert keys.event_data("previous", down=True) == (0xA00, (20 << 16) | 0xA00)
