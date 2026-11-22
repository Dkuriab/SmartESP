"""Звук: чтение и запись WAV 16 кГц моно int16, смена частоты, обрезка тишины."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import soxr

RATE = 16000


def read_wav(path: Path) -> np.ndarray:
    """WAV → int16 16 кГц моно (другая частота пересчитывается, стерео сводится)."""
    with wave.open(str(path), "rb") as src:
        rate, channels, width = src.getframerate(), src.getnchannels(), src.getsampwidth()
        raw = src.readframes(src.getnframes())
    if width != 2:
        raise ValueError(f"{path}: нужен 16-битный WAV")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return to_int16(resample(samples, rate))


def resample(samples: np.ndarray, rate: int) -> np.ndarray:
    """Float-звук частоты rate → 16 кГц."""
    return samples if rate == RATE else soxr.resample(samples, rate, RATE)


def to_int16(samples: np.ndarray) -> np.ndarray:
    return np.clip(samples * 32768.0, -32768, 32767).astype(np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    """int16 16 кГц моно → WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype("<i2").tobytes())


def trim_silence(samples: np.ndarray, threshold_db: float = -40.0, margin_s: float = 0.05) -> np.ndarray:
    """Обрезает тишину по краям по громкости окон 10 мс (порог от пика), оставляя поля margin_s."""
    if samples.size == 0:
        return samples
    frame = RATE // 100
    count = samples.size // frame
    if count == 0:
        return samples
    frames = samples[: count * frame].astype(np.float32).reshape(count, frame)
    energy = np.sqrt((frames**2).mean(axis=1)) + 1e-9
    loud = np.nonzero(20 * np.log10(energy / energy.max()) > threshold_db)[0]
    margin = int(margin_s * RATE)
    start = max(0, int(loud[0]) * frame - margin)
    end = min(samples.size, (int(loud[-1]) + 1) * frame + margin)
    return samples[start:end]
