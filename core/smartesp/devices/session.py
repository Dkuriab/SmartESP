"""Сессия одной подключённой колонки: запись вопроса, активный ход, отправка."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .connection import DeviceConnection


@dataclass
class Recording:
    """Звук вопроса одного хода, пока он не стал Utterance."""

    turn: int
    started_at: float  # clock() в момент wake
    pcm: bytearray = field(default_factory=bytearray)
    accepted: bool = False  # арбитр принял ход
    ended: bool = False  # пришёл utterance_end с речью


class Session:
    """Состояние колонки. Все отправки идут по очереди через замок."""

    def __init__(self, device_id: str, conn: DeviceConnection) -> None:
        self.device_id = device_id
        self.conn = conn
        self.recording: Recording | None = None
        self.active_turn: int | None = None  # принятый и ещё живой ход
        self.closed = False
        self._send_lock = asyncio.Lock()

    def is_live(self, turn: int) -> bool:
        """Ход turn принят, не закончен, и соединение не закрыто."""
        return not self.closed and self.active_turn == turn

    async def send_text(self, text: str) -> None:
        """Шлёт текст; ConnectionError, если соединение закрыто."""
        async with self._send_lock:
            if self.closed:
                raise ConnectionError("session closed")
            await self.conn.send_text(text)

    async def send_bytes(self, data: bytes) -> None:
        """Шлёт звук; ConnectionError, если соединение закрыто."""
        async with self._send_lock:
            if self.closed:
                raise ConnectionError("session closed")
            await self.conn.send_bytes(data)
