"""Тесты обработчика шёпота."""

import wave
from pathlib import Path

import numpy as np
import pytest

from smartesp.contracts import Stage, Utterance
from smartesp.stages import WhisperDetect

RATE = 16000
PRIVET = Path(__file__).parent.parent / "data" / "privet.wav"


def to_pcm(signal: np.ndarray) -> bytes:
    return (np.clip(signal, -1.0, 1.0) * 16000).astype("<i2").tobytes()


def voiced(seconds: float = 1.0, f0: float = 150.0) -> bytes:
    """Голосоподобный сигнал: основной тон и гармоники."""
    t = np.arange(int(RATE * seconds)) / RATE
    signal = np.zeros_like(t)
    for k in range(1, 6):
        signal += np.sin(2 * np.pi * f0 * k * t) / k
    return to_pcm(signal / 2)


def whispered(seconds: float = 1.0) -> bytes:
    """Шумоподобный сигнал без основного тона, как шёпот."""
    rng = np.random.default_rng(1)
    return to_pcm(rng.normal(0.0, 0.3, int(RATE * seconds)))


def utterance(pcm: bytes) -> Utterance:
    return Utterance(device_id="kitchen", turn=1, pcm=pcm, started_at=0.0, text="вопрос")


def test_satisfies_stage_contract() -> None:
    stage: Stage = WhisperDetect()
    assert stage.name == "whisper_detect"


async def test_voiced_speech_gets_no_annotation() -> None:
    assert await WhisperDetect().analyze(utterance(voiced())) == []


async def test_noise_like_whisper_is_annotated() -> None:
    annotations = await WhisperDetect().analyze(utterance(whispered()))
    assert len(annotations) == 1
    note = annotations[0]
    assert note.source == "whisper_detect"
    assert "шёпот" in note.text
    assert not note.to_model  # по умолчанию тихого ответа нет: пометка только в ленту
    assert isinstance(note.data["voiced_ratio"], float)
    assert note.data["voiced_ratio"] < 0.15


async def test_silence_gets_no_annotation() -> None:
    assert await WhisperDetect().analyze(utterance(bytes(RATE * 2))) == []


async def test_too_short_sound_gets_no_annotation() -> None:
    quiet = bytes(RATE * 2)  # 1 с тишины
    assert await WhisperDetect().analyze(utterance(quiet + whispered(0.1))) == []


async def test_empty_and_odd_pcm_do_not_raise() -> None:
    assert await WhisperDetect().analyze(utterance(b"")) == []
    assert await WhisperDetect().analyze(utterance(b"\x01")) == []


@pytest.mark.skipif(not PRIVET.exists(), reason="нет tests/data/privet.wav")
async def test_real_voice_is_not_whisper() -> None:
    with wave.open(str(PRIVET), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    assert await WhisperDetect().analyze(utterance(pcm)) == []


def low_voice_in_noise(f0: float = 80.0, snr_db: float = 5.0) -> bytes:
    """Низкий голос с лёгким дрожанием тона и шумом — не должен считаться шёпотом."""
    rng = np.random.default_rng(2)
    t = np.arange(RATE) / RATE
    phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 3 * t))) / RATE
    signal = np.zeros_like(t)
    for k in range(1, 8):
        signal += np.sin(k * phase) / k
    signal /= np.abs(signal).max() * 2
    noise = rng.normal(0.0, 1.0, RATE)
    noise *= np.sqrt(np.mean(signal**2) / 10 ** (snr_db / 10)) / np.sqrt(np.mean(noise**2))
    return to_pcm(signal + noise)


async def test_low_voice_in_noise_is_not_whisper() -> None:
    assert await WhisperDetect().analyze(utterance(low_voice_in_noise())) == []


async def test_coloured_noise_is_whisper() -> None:
    rng = np.random.default_rng(3)
    coloured = np.convolve(rng.normal(0.0, 0.3, RATE), np.ones(8) / 8, "same") * 3
    assert len(await WhisperDetect().analyze(utterance(to_pcm(coloured)))) == 1


def test_quiet_reply_off_by_default_no_hint() -> None:
    assert WhisperDetect().prompt_hint == ""


async def test_quiet_reply_on_tells_the_model() -> None:
    stage = WhisperDetect(quiet_reply=True)
    assert "[style:quiet]" in stage.prompt_hint
    (note,) = await stage.analyze(utterance(whispered()))
    assert note.to_model and "тихо" in note.text


async def test_whisper_never_changes_the_text() -> None:
    whisper = utterance(whispered())
    for stage in (WhisperDetect(), WhisperDetect(quiet_reply=True)):
        (note,) = await stage.analyze(whisper)
        assert whisper.text == "вопрос" and "вопрос" not in note.text
