"""Источники потока: проверка, названия, команда ffmpeg, звук Mac (список устройств AVFoundation)."""

from __future__ import annotations

import stat
from pathlib import Path

from smartesp.streams import capture_probe, ffmpeg_decoder
from smartesp.streams.capture import NO_FFMPEG, NO_INPUTS, match, parse_inputs
from smartesp.streams.sources import arguments, check_source, is_live, title_of

LISTING = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Pro Microphone
[AVFoundation indev @ 0x1] [1] BlackHole 2ch
Error opening input file .
"""


def fake_ffmpeg(tmp: Path, listing: str, pcm: bytes = b"") -> str:
    """Скрипт вместо ffmpeg: со списком устройств печатает listing в stderr, иначе pcm в stdout и
    свои аргументы — в файл args."""
    (tmp / "listing").write_text(listing)
    (tmp / "pcm").write_bytes(pcm)
    script = tmp / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *list_devices*) cat "{tmp}/listing" >&2; exit 1;; esac\n'
        f'echo "$@" > "{tmp}/args"\n'
        f'cat "{tmp}/pcm"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_check_source(tmp_path: Path) -> None:
    song = tmp_path / "Песня.MP3"
    song.write_bytes(b"ID3")
    assert check_source(str(song)) == ""
    assert check_source("https://radio.example/stream") == ""
    assert check_source("capture:BlackHole") == ""
    assert "имя устройства" in check_source("capture: ")
    assert "Нет файла" in check_source(str(tmp_path / "нет.mp3"))
    assert "Не звуковой" in check_source(str(tmp_path / "notes.txt"))
    assert "полный путь" in check_source("song.mp3")
    assert "Неверная ссылка" in check_source("http://")
    assert check_source("") != "" and check_source("/a\n.mp3") != ""


def test_titles_and_live() -> None:
    assert title_of("/Music/Кино/Группа крови.mp3") == "Группа крови"
    assert title_of("https://radio.example/rock") == "radio.example/rock"
    assert title_of("capture:BlackHole") == "Звук Mac"
    assert is_live("capture:BlackHole") and is_live("http://r/x") and not is_live("/a.mp3")


def test_arguments_per_kind() -> None:
    file = arguments("ff", "/Music/a.mp3", 12.5)
    assert file[file.index("-ss") + 1] == "12.500" and file[file.index("-i") + 1] == "file:/Music/a.mp3"
    assert file[file.index("-protocol_whitelist") + 1] == "file"
    assert file[-3:] == ["-ar", "16000", "pipe:1"]
    assert arguments("ff", "/Music/a.mp3", 0.0, 48000)[-3:] == ["-ar", "48000", "pipe:1"]
    radio = arguments("ff", "https://r/x", 99.0)
    assert (
        "-ss" not in radio
        and "-reconnect" in radio
        and "file" not in radio[radio.index("-protocol_whitelist") + 1]
    )
    mac = arguments("ff", "capture:1", 0.0)
    assert mac[mac.index("-f") + 1] == "avfoundation" and mac[mac.index("-i") + 1] == ":1"


def test_parse_and_match_inputs() -> None:
    inputs = parse_inputs(LISTING)
    assert inputs == [(0, "MacBook Pro Microphone"), (1, "BlackHole 2ch")]
    assert match(inputs, "blackhole") == (1, "BlackHole 2ch")
    assert match(inputs, "Loopback") is None


async def test_probe_explains_missing_parts(tmp_path: Path) -> None:
    assert await capture_probe(lambda: None)("capture:BlackHole") == NO_FFMPEG
    assert await capture_probe(lambda: None)("/a.mp3") == ""
    empty = fake_ffmpeg(tmp_path, "AVFoundation audio devices:\n")
    assert await capture_probe(lambda: empty)("capture:BlackHole") == NO_INPUTS
    full = fake_ffmpeg(tmp_path, LISTING)
    assert await capture_probe(lambda: full)("capture:BlackHole") == ""
    missing = await capture_probe(lambda: full)("capture:Loopback")
    assert "brew install --cask blackhole-2ch" in missing and "MacBook Pro Microphone" in missing


async def test_decoder_streams_whole_samples(tmp_path: Path) -> None:
    program = fake_ffmpeg(tmp_path, LISTING, pcm=b"\x01\x02\x03\x04\x05")
    decode = ffmpeg_decoder(lambda: program)
    pcm = b"".join([chunk async for chunk in decode("capture:blackhole", 0.0, 16000)])
    assert pcm == b"\x01\x02\x03\x04"  # нечётный хвост отброшен
    assert "-f avfoundation -i :1" in (tmp_path / "args").read_text()
    assert [chunk async for chunk in ffmpeg_decoder(lambda: None)("/a.mp3", 0.0, 16000)] == []
    assert [chunk async for chunk in decode("capture:Loopback", 0.0, 48000)] == []  # устройства нет
