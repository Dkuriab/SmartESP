"""Сессия одной подключённой колонки: запись вопроса, активный ход, отправка."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .connection import DeviceConnection


@dataclass
class Recording:
    """Звук вопроса одного хода колонки, пока он не стал Utterance."""

    esp_turn: int  # номер хода, выданный колонкой
    started_at: float  # clock() в момент wake
    pcm: bytearray = field(default_factory=bytearray)
    turn_id: int | None = None  # номер хода в хабе; задан, когда арбитр принял ход
    ended: bool = False  # пришёл utterance_end с речью


@dataclass(frozen=True)
class ActiveTurn:
    """Принятый и ещё живой ход: номер в хабе и номер колонки."""

    turn_id: int
    esp_turn: int


class Session:
    """Состояние колонки. Все отправки идут по очереди через замок."""

    def __init__(self, device_id: str, conn: DeviceConnection) -> None:
        self.device_id = device_id
        self.conn = conn
        self.recording: Recording | None = None
        self.active: ActiveTurn | None = None
        self.closed = False
        self._send_lock = asyncio.Lock()

    def is_live(self, turn_id: int) -> bool:
        """Ход хаба turn_id — активный ход этой сессии, и соединение не закрыто."""
        return not self.closed and self.active is not None and self.active.turn_id == turn_id

    async def send(self, frame: str | bytes, turn_id: int | None = None) -> bool:
        """Шлёт кадр (текст или звук) по очереди с другими отправками.

        turn_id задан — кадр уходит, только если этот ход ещё жив (проверка под замком,
        после ожидания очереди). Возвращает False, если кадр не отправлен: сессия закрыта,
        ход закончился или соединение оборвалось.
        """
        async with self._send_lock:
            if self.closed or (turn_id is not None and not self.is_live(turn_id)):
                return False
            try:
                if isinstance(frame, str):
                    await self.conn.send_text(frame)
                else:
                    await self.conn.send_bytes(frame)
            except ConnectionError:
                return False
            return True
