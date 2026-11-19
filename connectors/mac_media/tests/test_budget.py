"""Бюджет времени инструмента: зависший плеер не держит ответ дольше бюджета.

Хаб ядра ждёт инструмент 15 с; коннектор должен ответить раньше и честно.
"""

import asyncio
import time

import pytest

from mac_media_mcp.media import MediaError, MediaService
from mac_media_mcp.system import Track
from tests.fake_system import FakeSystem

HANG = 3600.0
BUDGET = 0.3
MUSIC_SILENT = "Приложение «Музыка» не отвечает. Возможно, macOS ждёт разрешения — проверь окно запроса."
SPOTIFY_SILENT = "Приложение Spotify не отвечает. Возможно, macOS ждёт разрешения — проверь окно запроса."


async def answer(system: FakeSystem, tool: str, *args: object) -> tuple[bool, str, float]:
    """Вызывает метод MediaService; (ошибка?, текст, сколько секунд заняло)."""
    media = MediaService(system, budget_s=BUDGET)
    started = time.monotonic()
    try:
        text = await getattr(media, tool)(*args)
        failed = False
    except MediaError as error:
        text, failed = str(error), True
    return failed, text, time.monotonic() - started


async def test_music_play_hung_music_answers_in_budget() -> None:
    failed, text, took = await answer(FakeSystem(delays={"Music": HANG}), "music_play", "кино")
    assert (failed, text) == (True, MUSIC_SILENT)
    assert took < BUDGET + 0.2


async def test_music_play_spotify_gets_only_remaining_budget() -> None:
    system = FakeSystem(has_spotify=True, delays={"Music": BUDGET * 0.6, "Spotify": HANG})
    failed, text, took = await answer(system, "music_play", "битлз")
    assert (failed, text) == (True, SPOTIFY_SILENT)
    assert took < BUDGET + 0.2


async def test_spent_budget_skips_next_call() -> None:
    system = FakeSystem()
    media = MediaService(system, budget_s=0)
    with pytest.raises(MediaError, match="не отвечает"):
        await media.volume_set(30)
    assert system.volume_calls == []


async def test_script_timeout_is_honest() -> None:
    failed, text, _ = await answer(FakeSystem(timeouts={"Music"}), "music_play", "кино")
    assert (failed, text) == (True, MUSIC_SILENT)


async def test_volume_hung_answers_in_budget() -> None:
    failed, text, took = await answer(FakeSystem(delays={"volume": HANG}), "volume_set", 30)
    assert (failed, text) == (True, "Mac не отвечает на команду звука.")
    assert took < BUDGET + 0.2


async def test_now_playing_hung_player_does_not_block_other() -> None:
    system = FakeSystem(
        running=["Music", "Spotify"], delays={"Music": HANG}, tracks={"Spotify": Track("Звезда", "Б")}
    )
    failed, text, took = await answer(system, "now_playing")
    assert (failed, text) == (False, "Сейчас играет: Б — «Звезда».")
    assert took < BUDGET + 0.2


async def test_now_playing_hung_player_is_not_silence() -> None:
    """Зависший плеер — честный ответ, а не «ничего не играет»."""
    system = FakeSystem(running=["Music"], delays={"Music": HANG})
    assert (await answer(system, "now_playing"))[:2] == (True, MUSIC_SILENT)


async def test_now_playing_failure_is_reported() -> None:
    system = FakeSystem(running=["Music"], failure="Не получилось управлять приложением «Музыка».")
    assert (await answer(system, "now_playing"))[:2] == (
        True,
        "Не получилось управлять приложением «Музыка».",
    )


async def test_now_playing_permission_beats_other_failure() -> None:
    system = FakeSystem(running=["Music", "Spotify"], denied={"Spotify"}, delays={"Music": HANG})
    failed, text, _ = await answer(system, "now_playing")
    assert failed
    assert text.startswith("Нет разрешения управлять приложением Spotify.")


async def test_default_budget_below_hub_timeout() -> None:
    from mac_media_mcp import media, osascript

    assert media.BUDGET_S == 10.0
    assert osascript.TIMEOUT_S == 5.0
    assert asyncio.iscoroutinefunction(MediaService(FakeSystem()).now_playing)
