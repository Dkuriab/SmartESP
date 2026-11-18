"""Тесты MlxWhisperSTT."""

import wave
from pathlib import Path

import numpy as np
import pytest

from smartesp.contracts import SpeechToText
from smartesp.stt import MlxWhisperSTT, pcm_to_float

DATA = Path(__file__).parent.parent / "data"


def test_pcm_to_float_scales() -> None:
    out = pcm_to_float(b"\x00\x80\xff\x7f")
    assert out.dtype == np.float32
    assert out[0] == -1.0
    assert out[1] == pytest.approx(0.99997, abs=1e-5)


async def test_empty_pcm_returns_empty_without_model() -> None:
    stt: SpeechToText = MlxWhisperSTT("unused-model", "ru")
    assert await stt.transcribe(b"") == ""


@pytest.mark.models
async def test_transcribes_russian() -> None:
    import time

    with wave.open(str(DATA / "privet.wav"), "rb") as w:
        pcm = w.readframes(w.getnframes())
    stt: SpeechToText = MlxWhisperSTT("mlx-community/whisper-large-v3-turbo", "ru")
    t0 = time.perf_counter()
    text = await stt.transcribe(pcm)
    print(f"transcribe took {time.perf_counter() - t0:.2f}s: {text!r}")
    assert "привет" in text.lower()
