"""Тесты SileroTTS."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from smartesp.contracts import TextToSpeech
from smartesp.stt import MlxWhisperSTT
from smartesp.tts import SileroTTS

HOME = Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp")
MODEL = HOME / "voices" / "silero" / "v5_ru.pt"


class FakeModel:
    """Подделка модели: запоминает вызовы apply_tts."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def apply_tts(self, **kwargs: Any) -> torch.Tensor:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return torch.tensor([0.1, -0.1] * 1200)


def make(monkeypatch: pytest.MonkeyPatch, model: FakeModel) -> SileroTTS:
    monkeypatch.setattr(SileroTTS, "_load", staticmethod(lambda path: model))
    return SileroTTS(Path("unused.pt"), "xenia")


async def collect(tts: TextToSpeech, text: str, style: str = "normal") -> bytes:
    return b"".join([c async for c in tts.synthesize(text, style)])


def test_styles(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, FakeModel()).styles() == ["normal", "quiet"]


async def test_empty_after_cleanup_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    tts = make(monkeypatch, model)
    assert await collect(tts, "😀") == b""
    assert model.calls == []


async def test_numbers_become_words(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    tts = make(monkeypatch, model)
    pcm = await collect(tts, "в 8 утра")
    assert pcm
    assert model.calls[0]["text"] == "в восемь утра"
    assert model.calls[0]["speaker"] == "xenia"
    assert model.calls[0]["sample_rate"] == 24000


async def test_quiet_uses_ssml_and_is_quieter(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    tts = make(monkeypatch, model)
    normal = await collect(tts, "привет", "normal")
    quiet = await collect(tts, "привет", "quiet")
    assert model.calls[1]["ssml_text"] == '<speak><prosody rate="slow">привет</prosody></speak>'
    assert "text" not in model.calls[1]

    def peak(pcm: bytes) -> int:
        return int(np.abs(np.frombuffer(pcm, dtype="<i2")).max())

    assert peak(quiet) < peak(normal) * 0.5


async def test_unknown_style_is_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    tts = make(monkeypatch, model)
    await collect(tts, "привет", "shout")
    assert "text" in model.calls[0]


async def test_model_error_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tts = make(monkeypatch, FakeModel(RuntimeError("boom")))
    with caplog.at_level(logging.ERROR):
        assert await collect(tts, "привет") == b""
    assert any(r.levelno == logging.ERROR for r in caplog.records)


async def test_warm_up_synthesizes(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    tts = make(monkeypatch, model)
    await tts.warm_up()
    assert model.calls[0]["text"] == "Привет."


needs_model = pytest.mark.skipif(not MODEL.exists(), reason=f"нет голоса Silero: {MODEL}")


@pytest.mark.models
@needs_model
async def test_silero_speaks_numbers() -> None:
    tts = SileroTTS(MODEL, "xenia")
    pcm = await collect(tts, "Будильник на 8 утра.")
    assert len(pcm) > 16000 * 2 * 0.8
    text = (await MlxWhisperSTT("mlx-community/whisper-large-v3-turbo", "ru").transcribe(pcm)).lower()
    assert "8" in text or "восем" in text


def _rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    return float(np.sqrt(np.mean(samples**2)))


@pytest.mark.models
@needs_model
async def test_silero_quiet_is_quieter_and_slower() -> None:
    tts = SileroTTS(MODEL, "xenia")
    text = "Тише, все уже спят."
    normal = await collect(tts, text, "normal")
    quiet = await collect(tts, text, "quiet")
    assert _rms(quiet) < _rms(normal) * 0.5
    assert len(quiet) > len(normal)


@pytest.mark.models
@needs_model
async def test_silero_concurrent_synthesis() -> None:
    tts = SileroTTS(MODEL, "xenia")
    a, b = await asyncio.gather(collect(tts, "Первый ответ."), collect(tts, "Второй ответ."))
    assert a
    assert b
