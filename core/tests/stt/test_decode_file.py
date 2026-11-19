"""Тесты разбора звукового файла по ходу (для проигрывания): подделка ffmpeg и настоящий ffmpeg."""

import asyncio
import io
import math
import struct
import subprocess
import time
import wave
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from smartesp.contracts import AskUnavailable, AudioUndecodable
from smartesp.stt import decode_file, find_ffmpeg
from smartesp.stt.decode import FILE_MAX_DURATION_S

FFMPEG = find_ffmpeg()
real_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="нет ffmpeg")


def fake_program(tmp_path: Path, script: str) -> str:
    """Исполняемый скрипт вместо ffmpeg."""
    path = tmp_path / "ffmpeg"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return str(path)


def tone_wav(seconds: float, rate: int = 48000, channels: int = 2) -> bytes:
    """WAV с тоном 440 Гц, 48 кГц стерео: ffmpeg должен привести к 16 кГц моно."""
    frames = int(seconds * rate)
    samples = (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames))
    data = b"".join(struct.pack("<h", s) * channels for s in samples)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(data)
    return buffer.getvalue()


async def collect(pcm: AsyncGenerator[bytes]) -> list[bytes]:
    return [chunk async for chunk in pcm]


@pytest.fixture
def song(tmp_path: Path) -> Path:
    path = tmp_path / "song.bin"
    path.write_bytes(b"RIFF")
    return path


async def test_chunks_keep_whole_samples(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, 'printf "abc"\nsleep 0.2\nprintf "def"\nprintf "g"\n')
    chunks = await collect(decode_file(song, ffmpeg=program))
    assert b"".join(chunks) == b"abcdef"  # нечётный хвост отрезан, куски не рвут отсчёты
    assert all(len(chunk) % 2 == 0 for chunk in chunks)


async def test_arguments_cap_duration_and_formats(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, 'printf "%s\\n" "$@"\n')
    output = b"".join(await collect(decode_file(song, ffmpeg=program))).decode()
    arguments = output.split("\n")
    assert arguments[arguments.index("-t") + 1] == str(FILE_MAX_DURATION_S)
    assert arguments[arguments.index("-format_whitelist") + 1] == "mp3,wav,ogg,mov,flac"
    assert arguments[arguments.index("-protocol_whitelist") + 1] == "file"
    assert arguments[arguments.index("-i") + 1] == f"file:{song}"


async def test_failure_before_sound_is_undecodable(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, 'echo "Invalid data" >&2\nexit 1\n')
    with pytest.raises(AudioUndecodable, match="MP3, WAV, OGG, M4A или FLAC"):
        await anext(decode_file(song, ffmpeg=program))


async def test_no_sound_is_undecodable(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, "exit 0\n")
    with pytest.raises(AudioUndecodable, match="нет звука"):
        await anext(decode_file(song, ffmpeg=program))


async def test_failure_after_sound_ends_stream(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, 'printf "abcd"\nexit 1\n')
    assert b"".join(await collect(decode_file(song, ffmpeg=program))) == b"abcd"


async def test_slow_start_is_undecodable(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, "exec sleep 30\n")
    with pytest.raises(AudioUndecodable, match="дольше"):
        await anext(decode_file(song, ffmpeg=program, timeout_s=0.2))


async def test_missing_program_is_unavailable(tmp_path: Path, song: Path) -> None:
    with pytest.raises(AskUnavailable, match="ffmpeg"):
        await anext(decode_file(song, ffmpeg=str(tmp_path / "nope")))


async def test_close_stops_program(tmp_path: Path, song: Path) -> None:
    program = fake_program(tmp_path, 'printf "abcd"\nexec sleep 30\n')
    pcm = decode_file(song, ffmpeg=program)
    assert await anext(pcm) == b"abcd"
    started = time.monotonic()
    await pcm.aclose()
    assert time.monotonic() - started < 5


async def test_close_with_unread_output_does_not_hang(tmp_path: Path, song: Path) -> None:
    # колонка забирает звук медленнее разбора: в трубе остаётся непрочитанное
    program = fake_program(tmp_path, "head -c 2000000 /dev/zero\nexec sleep 30\n")
    pcm = decode_file(song, ffmpeg=program)
    await anext(pcm)
    await asyncio.sleep(0.3)
    async with asyncio.timeout(5):
        await pcm.aclose()


def encode(source: Path, target: Path, *codec: str) -> Path | None:
    """Кодирует файл настоящим ffmpeg; кодировщика нет — None."""
    assert FFMPEG is not None
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *codec, str(target)]
    return target if subprocess.run(command, capture_output=True).returncode == 0 else None


@real_ffmpeg
async def test_real_wav_streams_16k_mono(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    path.write_bytes(tone_wav(1.0))
    pcm = b"".join(await collect(decode_file(path)))
    assert abs(len(pcm) - 32000) <= 64  # 1 с × 16000 × 2 байта


@real_ffmpeg
@pytest.mark.parametrize(
    ("name", "codec"), [("tone.mp3", ()), ("tone.m4a", ("-c:a", "aac")), ("tone.flac", ()), ("tone.ogg", ())]
)
async def test_real_formats_decode(tmp_path: Path, name: str, codec: tuple[str, ...]) -> None:
    source = tmp_path / "tone.wav"
    source.write_bytes(tone_wav(1.0))
    target = encode(source, tmp_path / name, *codec)
    if target is None:
        pytest.skip(f"ffmpeg не кодирует {name}")
    pcm = b"".join(await collect(decode_file(target)))
    assert abs(len(pcm) - 32000) <= 4000


@real_ffmpeg
async def test_real_other_format_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    source.write_bytes(tone_wav(0.5))
    target = encode(source, tmp_path / "tone.aiff")
    if target is None:
        pytest.skip("ffmpeg не кодирует AIFF")
    with pytest.raises(AudioUndecodable):
        await anext(decode_file(target))
