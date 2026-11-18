"""Договор: синтез речи."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class TextToSpeech(Protocol):
    """Текст и стиль в звук."""

    def styles(self) -> list[str]:
        """Возвращает имена доступных стилей озвучки."""
        ...

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        """Озвучивает текст в заданном стиле; отдаёт PCM 16 кГц s16le кусками."""
        ...
