"""Договор: то, что разговору нужно от колонок."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .audio import Utterance


class DevicePort(Protocol):
    """Порт к колонкам; реализует DeviceHub."""

    async def next_utterance(self) -> Utterance:
        """Ждёт следующую реплику от любой колонки."""
        ...

    def is_active(self, device_id: str, turn: int) -> bool:
        """Возвращает True, если ход turn колонки device_id ещё актуален."""
        ...

    async def play(self, device_id: str, turn: int, audio: AsyncIterator[bytes]) -> None:
        """Проигрывает поток PCM на колонке в рамках хода turn."""
        ...

    async def send_tone(self, device_id: str, name: str) -> None:
        """Просит колонку сыграть короткий сигнал по имени."""
        ...

    def device_name(self, device_id: str) -> str:
        """Возвращает человеческое имя колонки."""
        ...
