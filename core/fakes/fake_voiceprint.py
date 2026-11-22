"""Подделка отпечатков голоса: «голос» зашит в первый отсчёт PCM (voice_pcm)."""

from __future__ import annotations

import struct
import time

DIM = 8


def voice_pcm(voice: int, seconds: float = 2.0) -> bytes:
    """PCM s16le 16 кГц: первый отсчёт — номер голоса, дальше ровный звук (пик −6 дБ)."""
    count = int(16000 * seconds)
    return struct.pack("<h", voice) + struct.pack("<h", 16384) * (count - 1)


class FakeVoicePrint:
    """Отпечаток — единичный вектор по номеру голоса (голоса с разными номерами не похожи)."""

    model = "fake-model"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls = 0
        self._delay_s = delay_s

    def embed(self, pcm: bytes) -> list[float]:
        self.calls += 1
        if self._delay_s:
            time.sleep(self._delay_s)
        voice = struct.unpack("<h", pcm[:2])[0] if len(pcm) >= 2 else 0
        vector = [0.0] * DIM
        vector[voice % DIM] = 1.0
        return vector
