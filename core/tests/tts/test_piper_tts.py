"""Тесты PiperTTS и ресемплинга."""

import os
import wave
from pathlib import Path

import pytest

from smartesp.contracts import TextToSpeech
from smartesp.tts import PiperTTS, resample_s16

HOME = Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp")
VOICE = HOME / "voices" / "ru_RU-irina-medium.onnx"
DATA = Path(__file__).parent.parent / "data"


def test_resample_length() -> None:
    pcm = b"\x00\x00" * 22050
    out = resample_s16(pcm, 22050)
    assert abs(len(out) - 32000) <= 64


def test_resample_identity_when_same_rate() -> None:
    pcm = b"\x01\x02" * 100
    assert resample_s16(pcm, 16000) == pcm


@pytest.mark.models
async def test_synthesizes_russian() -> None:
    tts: TextToSpeech = PiperTTS(VOICE)
    assert tts.styles() == ["normal"]
    chunks = [c async for c in tts.synthesize("Привет, как дела?", "unknown-style")]
    pcm = b"".join(chunks)
    assert len(pcm) > 0.3 * 16000 * 2
    assert all(len(c) % 2 == 0 for c in chunks)
    target = DATA / "privet.wav"
    if target.exists():
        return
    DATA.mkdir(exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
