"""Тесты разбора звука через ffmpeg: подделка программы и (если есть) настоящий ffmpeg."""

import io
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from smartesp.contracts import AskUnavailable, AudioUndecodable
from smartesp.stt import decode_audio, find_ffmpeg

FFMPEG = find_ffmpeg()
real_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="нет ffmpeg")


def fake_program(tmp_path: Path, script: str) -> str:
    """Исполняемый скрипт вместо ffmpeg."""
    path = tmp_path / "ffmpeg"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return str(path)


def tone_wav(seconds: float, rate: int = 48000, channels: int = 2) -> bytes:
    """WAV с тоном 440 Гц: другая частота и стерео — ffmpeg должен привести к 16 кГц моно."""
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


async def test_program_output_is_pcm(tmp_path: Path) -> None:
    program = fake_program(tmp_path, 'cat > /dev/null\nprintf "abcde"\n')
    assert await decode_audio(b"OggS", ffmpeg=program) == b"abcd"  # нечётный хвост отрезан


async def test_program_failure_is_undecodable(tmp_path: Path) -> None:
    program = fake_program(tmp_path, 'cat > /dev/null\necho "Invalid data" >&2\nexit 1\n')
    with pytest.raises(AudioUndecodable, match="OGG/Opus или WAV"):
        await decode_audio(b"junk", ffmpeg=program)


async def test_slow_program_is_killed(tmp_path: Path) -> None:
    program = fake_program(tmp_path, "exec sleep 30\n")
    with pytest.raises(AudioUndecodable, match="дольше"):
        await decode_audio(b"OggS", ffmpeg=program, timeout_s=0.2)


async def test_missing_program_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(AskUnavailable, match="ffmpeg"):
        await decode_audio(b"OggS", ffmpeg=str(tmp_path / "nope"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_ffmpeg(places=()) is None
    assert find_ffmpeg(places=(str(tmp_path / "nope"), fake_program(tmp_path, "exit 0\n"))) is not None


@real_ffmpeg
async def test_real_wav_becomes_16k_mono() -> None:
    pcm = await decode_audio(tone_wav(0.5))
    assert abs(len(pcm) - 16000) <= 64  # 0,5 с × 16000 × 2 байта


@real_ffmpeg
async def test_real_ogg_opus_decodes() -> None:
    assert FFMPEG is not None
    encode = [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus"]
    result = subprocess.run([*encode, "-f", "ogg", "pipe:1"], input=tone_wav(1.0), capture_output=True)
    if result.returncode != 0:
        pytest.skip("ffmpeg без libopus")
    pcm = await decode_audio(result.stdout)
    assert abs(len(pcm) - 32000) <= 2000


@real_ffmpeg
async def test_real_garbage_is_undecodable() -> None:
    with pytest.raises(AudioUndecodable):
        await decode_audio(b"this is not audio at all" * 10)


@real_ffmpeg
async def test_real_nested_inputs_are_refused(tmp_path: Path) -> None:
    # списки concat и HLS со ссылкой на файл: ffmpeg не должен открывать вложенные адреса
    local = tmp_path / "local.wav"
    local.write_bytes(tone_wav(0.5))
    for data in (
        f"ffconcat version 1.0\nfile '{local}'\n".encode(),
        f"#EXTM3U\n#EXTINF:1,\nfile://{local}\n#EXT-X-ENDLIST\n".encode(),
    ):
        with pytest.raises(AudioUndecodable):
            await decode_audio(data)
