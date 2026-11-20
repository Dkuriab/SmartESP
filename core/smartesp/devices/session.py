"""Сессия одной подключённой колонки: запись вопроса, активный ход, отправка."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

from smartesp.contracts import Delivery

from .connection import DeviceConnection
from .messages import Hello, parse_message
from .progress import ReplyProgress

CORE_TURN_BIT = 0x80000000  # старший бит: номер хода выдало ядро (announce, listen), а не колонка


@dataclass
class Recording:
    """Звук вопроса одного хода колонки, пока он не стал Utterance."""

    esp_turn: int  # номер хода, выданный колонкой
    started_at: float  # clock() в момент wake
    pcm: bytearray = field(default_factory=bytearray)
    turn_id: int | None = None  # номер хода в хабе; задан, когда арбитр принял ход
    ended: bool = False  # пришёл utterance_end с речью
    origin: str = "wake"  # "listen" — запись хода, начатого командой ядра


@dataclass(frozen=True)
class ActiveTurn:
    """Принятый и ещё живой ход: номер в хабе и номер колонки."""

    turn_id: int
    esp_turn: int


class Session:
    """Состояние колонки. Все отправки идут по очереди через замок."""

    def __init__(self, device_id: str, conn: DeviceConnection, protocol: int = 1) -> None:
        self.device_id = device_id
        self.conn = conn
        self.protocol = protocol
        self.recording: Recording | None = None
        self.active: ActiveTurn | None = None
        self.progress: ReplyProgress | None = None  # звук последнего начатого ответа
        self.closed = False
        self._send_lock = asyncio.Lock()
        self._core_turns = itertools.count(1)
        self._outcomes: dict[int, asyncio.Future[Delivery]] = {}  # ожидания итога по номеру колонки

    def is_live(self, turn_id: int) -> bool:
        """Ход хаба turn_id — активный ход этой сессии, и соединение не закрыто."""
        return not self.closed and self.active is not None and self.active.turn_id == turn_id

    def is_idle(self) -> bool:
        """Сессия открыта, и у хаба нет на ней ни записи, ни активного хода."""
        return not self.closed and self.recording is None and self.active is None

    def next_core_turn(self) -> int:
        """Номер следующего хода ядра в этой сессии: 0x80000000 | n, n с 1."""
        return CORE_TURN_BIT | next(self._core_turns)

    def outcome(self, turn_id: int) -> asyncio.Future[Delivery] | None:
        """Ожидание итога активного хода хаба turn_id; None — ход уже не активен.

        Итог задаёт end_turn: playback_done, barge_in, busy, отмена ядром, закрытие сессии.
        """
        if self.active is None or not self.is_live(turn_id):
            return None
        future = self._outcomes.get(self.active.esp_turn)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._outcomes[self.active.esp_turn] = future
        return future

    def end_turn(self, esp_turn: int, outcome: Delivery) -> bool:
        """Заканчивает активный ход колонки esp_turn с итогом outcome. False — он не активен."""
        if self.active is None or self.active.esp_turn != esp_turn:
            return False
        self.active = None
        future = self._outcomes.pop(esp_turn, None)
        if future is not None and not future.done():
            future.set_result(outcome)
        return True

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


async def wait_hello(conn: DeviceConnection) -> tuple[Session, str]:
    """Ждёт hello; всё, что пришло раньше, игнорирует. Возвращает сессию и версию прошивки."""
    while True:
        frame = await conn.receive()
        message = parse_message(frame) if isinstance(frame, str) else None
        if isinstance(message, Hello):
            device_id = message.device_id or f"legacy:{conn.remote}"
            return Session(device_id, conn, message.protocol), message.fw
