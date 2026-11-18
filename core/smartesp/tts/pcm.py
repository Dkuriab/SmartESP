"""Преобразования PCM для голосов: float → s16 и громкость."""

import numpy as np

# Множитель громкости для тихой речи (шёпот и т. п.).
QUIET_VOLUME = 0.35


def float_to_s16(samples: np.ndarray) -> bytes:
    """Переводит float-сэмплы [-1, 1] в PCM s16le (значения вне диапазона обрезаются)."""
    clipped = np.clip(samples.astype(np.float32), -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


def scale_volume(pcm: bytes, factor: float) -> bytes:
    """Умножает громкость PCM s16le на factor с обрезкой до диапазона int16."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    scaled = np.clip(samples * factor, -32768, 32767)
    return scaled.astype("<i2").tobytes()
