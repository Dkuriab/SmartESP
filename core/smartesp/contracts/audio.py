"""Договор: аудио и реплика пользователя."""

from __future__ import annotations

from dataclasses import dataclass

SAMPLE_RATE = 16000  # Гц, формат звука везде: s16le, моно


@dataclass(frozen=True)
class Utterance:
    """Одна реплика пользователя, пришедшая с колонки."""

    device_id: str
    turn: int
    pcm: bytes  # s16le, 16 кГц, моно
    started_at: float  # time.monotonic() начала слова
    text: str = ""
    origin: str = "wake"  # "wake" — ход по слову пробуждения; "listen" — колонку включило ядро
