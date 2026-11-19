"""Инструменты через клиентскую сессию SDK в памяти, система — подделка."""

from mcp import Client
from mcp.types import TextContent

from mac_media_mcp.server import build_server
from mac_media_mcp.system import Track
from tests.fake_system import FakeSystem

TOOLS = {
    "media_play_pause",
    "media_next",
    "media_previous",
    "media_now_playing",
    "volume_get",
    "volume_set",
    "volume_change",
    "output_devices",
    "output_set",
    "music_play",
}

AUTOMATION_HINT = "Разреши в Настройках → Конфиденциальность → Автоматизация."


async def call(system: FakeSystem, name: str, args: dict[str, object] | None = None) -> tuple[bool, str]:
    async with Client(build_server(system)) as client:
        result = await client.call_tool(name, args or {})
    block = result.content[0]
    assert isinstance(block, TextContent)
    # Ядро снимает английскую приставку SDK у ошибки — снимаем и здесь.
    return result.is_error, block.text.removeprefix(f"Error executing tool {name}: ")


async def test_tools_listed_in_russian() -> None:
    async with Client(build_server(FakeSystem())) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert tool.description
        assert any("а" <= ch.lower() <= "я" for ch in tool.description)


# --- медиа-клавиши ---


async def test_media_keys_pressed() -> None:
    system = FakeSystem()
    assert await call(system, "media_play_pause") == (False, "Переключила воспроизведение.")
    assert await call(system, "media_next") == (False, "Следующий трек.")
    assert await call(system, "media_previous") == (False, "Предыдущий трек.")
    assert system.pressed == ["play_pause", "next", "previous"]


async def test_media_keys_permission_denied() -> None:
    system = FakeSystem(denied={"keys"})
    is_error, text = await call(system, "media_next")
    assert is_error
    assert text == (
        "Нет разрешения нажимать медиа-клавиши. "
        "Разреши в Настройках → Конфиденциальность → Универсальный доступ."
    )
    assert system.pressed == []


async def test_system_failure_is_tool_error() -> None:
    is_error, text = await call(FakeSystem(failure="Звук не отвечает."), "media_play_pause")
    assert (is_error, text) == (True, "Звук не отвечает.")


# --- что играет ---


async def test_now_playing_nothing_running() -> None:
    assert await call(FakeSystem(), "media_now_playing") == (False, "Не вижу, что сейчас играет.")


async def test_now_playing_music() -> None:
    system = FakeSystem(running=["Music"], tracks={"Music": Track("Группа крови", "Кино")})
    assert await call(system, "media_now_playing") == (False, "Сейчас играет: Кино — «Группа крови».")


async def test_now_playing_paused_without_artist() -> None:
    system = FakeSystem(running=["Music"], tracks={"Music": Track("Подкаст", "", playing=False)})
    assert await call(system, "media_now_playing") == (False, "На паузе: «Подкаст».")


async def test_now_playing_prefers_playing_player() -> None:
    system = FakeSystem(
        running=["Music", "Spotify"],
        tracks={"Music": Track("Тишина", "А", playing=False), "Spotify": Track("Звезда", "Б")},
    )
    assert await call(system, "media_now_playing") == (False, "Сейчас играет: Б — «Звезда».")


async def test_now_playing_stopped_player() -> None:
    system = FakeSystem(running=["Music"])
    assert await call(system, "media_now_playing") == (False, "Не вижу, что сейчас играет.")


async def test_now_playing_permission_denied() -> None:
    system = FakeSystem(running=["Music"], denied={"Music"})
    is_error, text = await call(system, "media_now_playing")
    assert is_error
    assert text == f"Нет разрешения управлять приложением «Музыка». {AUTOMATION_HINT}"


async def test_now_playing_other_player_answers_despite_denied() -> None:
    system = FakeSystem(running=["Music", "Spotify"], denied={"Music"}, tracks={"Spotify": Track("Звезда")})
    assert await call(system, "media_now_playing") == (False, "Сейчас играет: «Звезда».")


# --- громкость ---


async def test_volume_get() -> None:
    assert await call(FakeSystem(volume=40), "volume_get") == (False, "Громкость 40 процентов.")
    assert await call(FakeSystem(volume=21), "volume_get") == (False, "Громкость 21 процент.")
    assert await call(FakeSystem(volume=3), "volume_get") == (False, "Громкость 3 процента.")


async def test_volume_get_not_adjustable() -> None:
    is_error, text = await call(FakeSystem(volume=None), "volume_get")
    assert (is_error, text) == (True, "У этого устройства вывода громкость не регулируется.")


async def test_volume_set() -> None:
    system = FakeSystem()
    assert await call(system, "volume_set", {"percent": 30}) == (False, "Громкость 30 процентов.")
    assert system.volume_calls == [30]


async def test_volume_set_out_of_range() -> None:
    for percent in (-1, 101, 1000):
        system = FakeSystem()
        is_error, text = await call(system, "volume_set", {"percent": percent})
        assert is_error
        assert "от 0 до 100" in text
        assert system.volume_calls == []


async def test_volume_set_rejects_fraction() -> None:
    system = FakeSystem()
    is_error, _ = await call(system, "volume_set", {"percent": 30.5})
    assert is_error
    assert system.volume_calls == []


async def test_volume_change_clamped() -> None:
    system = FakeSystem(volume=90)
    assert await call(system, "volume_change", {"delta": 20}) == (False, "Громкость 100 процентов.")
    system = FakeSystem(volume=10)
    assert await call(system, "volume_change", {"delta": -15}) == (False, "Громкость 0 процентов.")
    assert system.volume_calls == [0]


async def test_volume_change_already_at_limit() -> None:
    system = FakeSystem(volume=100)
    assert await call(system, "volume_change", {"delta": 10}) == (False, "Громкость уже на максимуме.")
    system = FakeSystem(volume=0)
    assert await call(system, "volume_change", {"delta": -10}) == (False, "Звук уже выключен.")
    assert system.volume_calls == []


async def test_volume_change_bad_delta() -> None:
    system = FakeSystem()
    is_error, text = await call(system, "volume_change", {"delta": 150})
    assert is_error
    assert "от -100 до 100" in text


# --- устройства вывода ---


async def test_output_devices() -> None:
    assert await call(FakeSystem(), "output_devices") == (
        False,
        "Устройства вывода: Динамики MacBook Pro (сейчас), JBL Flip 5.",
    )


async def test_output_devices_empty() -> None:
    assert await call(FakeSystem(devices=[], current_output=None), "output_devices") == (
        False,
        "Не вижу устройств вывода звука.",
    )


async def test_output_set_partial_case_insensitive() -> None:
    system = FakeSystem()
    assert await call(system, "output_set", {"name": "jbl"}) == (False, "Звук теперь через JBL Flip 5.")
    assert system.current_output == "JBL Flip 5"


async def test_output_set_exact_wins_over_partial() -> None:
    system = FakeSystem(devices=["JBL", "JBL Flip 5"], current_output="JBL Flip 5")
    assert await call(system, "output_set", {"name": "jbl"}) == (False, "Звук теперь через JBL.")


async def test_output_set_ambiguous() -> None:
    system = FakeSystem(devices=["Динамики MacBook Pro", "Динамики LG", "JBL"])
    assert await call(system, "output_set", {"name": "динамики"}) == (
        False,
        "Уточни: Динамики MacBook Pro или Динамики LG?",
    )
    assert system.current_output == "Динамики MacBook Pro"


async def test_output_set_unknown() -> None:
    is_error, text = await call(FakeSystem(), "output_set", {"name": "телевизор"})
    assert is_error
    assert text == "Не нашла устройство «телевизор». Есть: Динамики MacBook Pro, JBL Flip 5."


async def test_output_set_already_current() -> None:
    system = FakeSystem()
    assert await call(system, "output_set", {"name": "динамики"}) == (
        False,
        "Звук и так идёт через Динамики MacBook Pro.",
    )


async def test_output_set_yo_insensitive() -> None:
    system = FakeSystem(devices=["Ёлка", "JBL"], current_output="JBL")
    assert await call(system, "output_set", {"name": "елка"}) == (False, "Звук теперь через Ёлка.")


# --- музыка ---


async def test_music_play_found() -> None:
    system = FakeSystem(library={"кино": Track("Группа крови", "Кино")})
    assert await call(system, "music_play", {"query": "кино"}) == (
        False,
        "Включаю: Кино — «Группа крови».",
    )


async def test_music_play_not_found_without_spotify() -> None:
    system = FakeSystem()
    assert await call(system, "music_play", {"query": "битлз"}) == (
        False,
        "В медиатеке не нашла «битлз».",
    )


async def test_music_play_falls_back_to_spotify() -> None:
    system = FakeSystem(has_spotify=True)
    assert await call(system, "music_play", {"query": "битлз"}) == (
        False,
        "В медиатеке не нашла, ищу «битлз» в Spotify.",
    )
    assert system.spotify_queries == ["битлз"]


async def test_music_play_empty_query() -> None:
    is_error, text = await call(FakeSystem(), "music_play", {"query": "  "})
    assert (is_error, text) == (True, "Скажи, что включить.")


async def test_music_play_permission_denied() -> None:
    system = FakeSystem(denied={"Music"})
    is_error, text = await call(system, "music_play", {"query": "кино"})
    assert is_error
    assert text == f"Нет разрешения управлять приложением «Музыка». {AUTOMATION_HINT}"


async def test_music_play_spotify_permission_denied() -> None:
    system = FakeSystem(has_spotify=True, denied={"Spotify"})
    is_error, text = await call(system, "music_play", {"query": "битлз"})
    assert is_error
    assert text == f"Нет разрешения управлять приложением Spotify. {AUTOMATION_HINT}"
