"""Фиксированные AppleScript коннектора и разбор их ответов.

Никакой подстановки в текст: изменяемые данные приходят в `on run argv`.
Ответ про трек — строки «состояние, название, исполнитель».
"""

from mac_media_mcp.system import Track

# Громкость выхода; у устройства без регулировки — «missing value».
VOLUME_GET = "output volume of (get volume settings)"

# Громкость из argv: целое, проверенное заранее (0–100); ненулевая ещё и снимает «без звука».
VOLUME_SET = """on run argv
	set n to (item 1 of argv) as integer
	set volume output volume n
	if n > 0 then set volume without output muted
end run"""

_NOW_PLAYING = """tell application "{app}"
	if player state is stopped then return ""
	set t to current track
	return (player state as text) & linefeed & (name of t) & linefeed & (artist of t)
end tell"""

MUSIC_NOW_PLAYING = _NOW_PLAYING.format(app="Music")
SPOTIFY_NOW_PLAYING = _NOW_PLAYING.format(app="Spotify")

# Поиск в своей медиатеке (library playlist 1 — «Медиатека» при любом языке системы).
MUSIC_SEARCH_PLAY = """on run argv
	set q to item 1 of argv
	tell application "Music"
		set found to search library playlist 1 for q
		if found is {} then return ""
		set t to item 1 of found
		play t
		return "playing" & linefeed & (name of t) & linefeed & (artist of t)
	end tell
end run"""

# Spotify: адрес поиска «spotify:search:…» из argv (запрос уже закодирован).
SPOTIFY_SEARCH_PLAY = """on run argv
	tell application "Spotify" to play track (item 1 of argv)
end run"""


def parse_volume(output: str) -> int | None:
    """«40» → 40; «missing value» и прочее непонятное → None."""
    text = output.strip()
    if not text.isdigit():
        return None
    return max(0, min(100, int(text)))


def parse_track(output: str) -> Track | None:
    """Строки «состояние / название / исполнитель» → Track; пусто → None."""
    lines = output.split("\n")
    if len(lines) < 2 or not lines[1].strip():
        return None
    state, name = lines[0].strip(), lines[1].strip()
    artist = lines[2].strip() if len(lines) > 2 else ""
    if artist == "missing value":
        artist = ""
    return Track(name=name, artist=artist, playing=state == "playing")
