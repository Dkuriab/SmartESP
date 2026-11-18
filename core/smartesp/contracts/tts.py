"""Договор: синтез речи."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceInfo:
    """Голос из каталога: вид, имя, подпись, размер загрузки и наличие на диске."""

    kind: str
    voice: str
    title: str
    size_mb: int
    downloaded: bool


class VoiceNotDownloadedError(Exception):
    """Голос ещё не скачан, поэтому им нельзя говорить (API отвечает 409)."""


class TextToSpeech(Protocol):
    """Текст и стиль в звук."""

    def styles(self) -> list[str]:
        """Возвращает имена доступных стилей озвучки."""
        ...

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        """Озвучивает текст в заданном стиле; отдаёт PCM 16 кГц s16le кусками."""
        ...
