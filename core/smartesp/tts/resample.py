"""Ресемплинг PCM s16le моно."""

import numpy as np
import soxr


def resample_s16(pcm: bytes, rate_in: int, rate_out: int = 16000) -> bytes:
    """Приводит PCM s16le моно из rate_in к rate_out (по умолчанию 16 кГц)."""
    if rate_in == rate_out:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16)
    out = soxr.resample(samples, rate_in, rate_out)
    return out.astype(np.int16).tobytes()
