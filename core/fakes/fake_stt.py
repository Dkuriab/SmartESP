"""Подделка распознавания речи: всегда возвращает заданный текст."""

from __future__ import annotations


class FakeSTT:
    def __init__(self, text: str) -> None:
        self._text = text

    async def transcribe(self, pcm: bytes) -> str:
        return self._text
