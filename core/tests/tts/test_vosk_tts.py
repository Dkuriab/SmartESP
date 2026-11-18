"""Тесты VoskTTS."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from smartesp.contracts import TextToSpeech
from smartesp.stt import MlxWhisperSTT
from smartesp.tts import VoskTTS

HOME = Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp")
MODEL_DIR = HOME / "voices" / "vosk" / "vosk-model-tts-ru-0.9-multi"

CONFIG = {"audio": {"sample_rate": 22050}, "speaker_id_map": {"female_0": 0, "female_1": 1, "male_0": 3}}


class FakeSynth:
    """Подделка синтезатора: запоминает вызовы synth_audio."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def synth_audio(self, text: str, **kwargs: Any) -> np.ndarray:
        self.calls.append({"text": text, **kwargs})
        if self.error:
            raise self.error
        return np.array([3000, -3000] * 1200, dtype=np.int16)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    (tmp_path / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    return tmp_path


def make(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path, synth: FakeSynth, speaker: str = "female_1"
) -> VoskTTS:
    monkeypatch.setattr(VoskTTS, "_load", staticmethod(lambda path: synth))
    return VoskTTS(model_dir, speaker)


async def collect(tts: TextToSpeech, text: str, style: str = "normal") -> bytes:
    return b"".join([c async for c in tts.synthesize(text, style)])


def test_styles(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    assert make(monkeypatch, model_dir, FakeSynth()).styles() == ["normal", "quiet"]


def test_unknown_speaker_lists_known(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    with pytest.raises(ValueError, match="female_0") as info:
        make(monkeypatch, model_dir, FakeSynth(), "male_9")
    assert "male_9" in str(info.value)


def test_unknown_speaker_does_not_load_model(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    def boom(path: Path) -> Any:
        raise AssertionError("модель не должна грузиться")

    monkeypatch.setattr(VoskTTS, "_load", staticmethod(boom))
    with pytest.raises(ValueError):
        VoskTTS(model_dir, "male_9")


async def test_empty_after_cleanup_yields_nothing(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    assert await collect(tts, "😀") == b""
    assert synth.calls == []


async def test_punctuation_only_is_not_synthesized(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    assert await collect(tts, "Wi-Fi!") == b""
    assert synth.calls == []


async def test_latin_and_digits_are_removed(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    assert await collect(tts, "Подключи Wi-Fi на 5 минут.")
    text = synth.calls[0]["text"]
    assert "пять" in text
    assert not any(c.isdigit() or ("a" <= c.lower() <= "z") for c in text)
    assert synth.calls[0]["speaker_id"] == 1


async def test_quiet_is_slower_and_quieter(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    normal = await collect(tts, "привет", "normal")
    quiet = await collect(tts, "привет", "quiet")
    assert synth.calls[0].get("speech_rate") is None
    assert synth.calls[1]["speech_rate"] == 0.87

    def peak(pcm: bytes) -> int:
        return int(np.abs(np.frombuffer(pcm, dtype="<i2")).max())

    assert peak(quiet) < peak(normal) * 0.5


async def test_unknown_style_is_normal(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    await collect(tts, "привет", "shout")
    assert synth.calls[0].get("speech_rate") is None


async def test_output_is_16k(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    tts = make(monkeypatch, model_dir, FakeSynth())
    pcm = await collect(tts, "привет")
    assert abs(len(pcm) // 2 - round(2400 * 16000 / 22050)) <= 2


async def test_synth_error_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tts = make(monkeypatch, model_dir, FakeSynth(KeyError("5")))
    with caplog.at_level(logging.ERROR):
        assert await collect(tts, "привет") == b""
    assert any(r.levelno == logging.ERROR for r in caplog.records)


async def test_warm_up_synthesizes(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    synth = FakeSynth()
    tts = make(monkeypatch, model_dir, synth)
    await tts.warm_up()
    assert synth.calls[0]["text"] == "Привет."


needs_model = pytest.mark.skipif(not MODEL_DIR.exists(), reason=f"нет голоса Vosk: {MODEL_DIR}")


def _rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    return float(np.sqrt(np.mean(samples**2)))


@pytest.mark.models
@needs_model
async def test_vosk_speaks_numbers() -> None:
    tts = VoskTTS(MODEL_DIR, "female_1")
    pcm = await collect(tts, "Будильник на 8 утра.")
    assert len(pcm) > 16000 * 2 * 0.8
    text = (await MlxWhisperSTT("mlx-community/whisper-large-v3-turbo", "ru").transcribe(pcm)).lower()
    assert "8" in text or "восем" in text


@pytest.mark.models
@needs_model
async def test_vosk_quiet_is_quieter_and_longer() -> None:
    tts = VoskTTS(MODEL_DIR, "female_1")
    text = "Тише, все уже спят."
    normal = await collect(tts, text, "normal")
    quiet = await collect(tts, text, "quiet")
    assert _rms(quiet) < _rms(normal) * 0.5
    assert len(quiet) > len(normal)


@pytest.mark.models
@needs_model
async def test_vosk_survives_symbols() -> None:
    tts = VoskTTS(MODEL_DIR, "female_1")
    assert await collect(tts, "Привет, 😀 Wi-Fi № 5!")


@pytest.mark.models
@needs_model
async def test_vosk_concurrent_synthesis() -> None:
    tts = VoskTTS(MODEL_DIR, "female_1")
    a, b = await asyncio.gather(collect(tts, "Первый ответ."), collect(tts, "Второй ответ."))
    assert a
    assert b
