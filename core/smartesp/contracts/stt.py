"""Договор: распознавание речи."""

from __future__ import annotations

from typing import Protocol


class SpeechToText(Protocol):
    """Звук в текст."""

    async def transcribe(self, pcm: bytes) -> str:
        """Распознаёт PCM (s16le, 16 кГц, моно) и возвращает текст."""
        ...
