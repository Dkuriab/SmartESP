"""Подготовка звука сигнала: тишина по краям прочь, не длиннее 3 с, пик как у встроенных, края без щелчков."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np

from smartesp.contracts import SAMPLE_RATE

MAX_SAMPLES = 3 * SAMPLE_RATE  # 3 с — предел колонки (96 000 байт)
PEAK = 0.4  # пик, доля шкалы: как у встроенных звуков (tools/make_sounds.py, 0,22–0,40)
SILENCE_DB = -45.0  # тише пика на столько — тишина по краям
FLOOR = 4 / 32768  # пик ниже — в файле нет звука
FADE_IN_S = 0.005
FADE_OUT_S = 0.02
CUT_FADE_S = 0.05  # спад, если звук обрезан по длине


@dataclass(frozen=True)
class Prepared:
    """Готовый звук: PCM s16le 16 кГц моно и обрезан ли он до MAX_SAMPLES."""

    pcm: bytes
    trimmed: bool


def prepare_sound(pcm: bytes) -> Prepared | None:
    """PCM s16le 16 кГц моно → звук для колонки; в нём нет звука — None."""
    samples = np.frombuffer(pcm[: len(pcm) & ~1], dtype="<i2").astype(np.float64) / 32768
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if peak < FLOOR:
        return None
    loud = np.flatnonzero(np.abs(samples) >= peak * 10 ** (SILENCE_DB / 20))
    samples = samples[loud[0] : loud[-1] + 1]
    trimmed = samples.size > MAX_SAMPLES
    if trimmed:
        samples = samples[:MAX_SAMPLES]
    samples = samples * (PEAK / float(np.abs(samples).max()))
    _fade(samples, FADE_IN_S, start=True)
    _fade(samples, CUT_FADE_S if trimmed else FADE_OUT_S, start=False)
    return Prepared(np.round(samples * 32767).astype("<i2").tobytes(), trimmed)


def _fade(samples: np.ndarray, seconds: float, *, start: bool) -> None:
    """Косинусное нарастание (start) или спад на краю, на месте."""
    count = min(samples.size, max(1, int(seconds * SAMPLE_RATE)))
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(count) / count)
    if start:
        samples[:count] *= ramp
    else:
        samples[-count:] *= ramp[::-1]


def to_wav(pcm: bytes) -> bytes:
    """PCM s16le 16 кГц моно → WAV для прослушивания в браузере."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue()
