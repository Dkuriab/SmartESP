"""Отправка ответа на колонку: reply_start → звук кусками с темпом → reply_end."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator

from smartesp.contracts import SAMPLE_RATE

from .messages import reply_end, reply_start
from .session import Session

CHUNK_BYTES = 4096  # размер звукового кадра к колонке
AHEAD_S = 10.0  # не больше стольких секунд звука впереди воспроизведения
PACE_STEP_S = 0.05  # как часто проверять темп и жив ли ход, пока ждём
BYTES_PER_S = SAMPLE_RATE * 2  # s16le, моно


def _pieces(chunk: bytes) -> Iterator[bytes]:
    """Режет кусок на кадры не длиннее CHUNK_BYTES."""
    for start in range(0, len(chunk), CHUNK_BYTES):
        yield chunk[start : start + CHUNK_BYTES]


class _Pacer:
    """Следит, чтобы отправленный звук не уходил дальше AHEAD_S вперёд часов."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._start = clock()
        self._sent_s = 0.0

    def ahead(self) -> float:
        """Сколько секунд звука отправлено сверх прошедшего времени."""
        return self._sent_s - (self._clock() - self._start)

    def add(self, size: int) -> None:
        """Учитывает отправленный кадр размером size байт."""
        self._sent_s += size / BYTES_PER_S


async def send_reply(
    session: Session, turn: int, audio: AsyncIterator[bytes], clock: Callable[[], float]
) -> None:
    """Шлёт ответ хода turn. Ход закончился или связь оборвалась — тихо выходит без reply_end.

    Ошибки самого источника звука (audio) не глотаются — они уходят вызывающему.
    """
    if not await _send_text(session, turn, reply_start(turn)):
        return
    pacer = _Pacer(clock)
    async for chunk in audio:
        for piece in _pieces(chunk):
            if not await _send_piece(session, turn, piece, pacer):
                return
    await _send_text(session, turn, reply_end(turn))


async def _send_text(session: Session, turn: int, text: str) -> bool:
    """Шлёт текст, пока ход жив. False — ход закончился или связь оборвалась."""
    if not session.is_live(turn):
        return False
    try:
        await session.send_text(text)
    except ConnectionError:
        return False
    return True


async def _send_piece(session: Session, turn: int, piece: bytes, pacer: _Pacer) -> bool:
    """Ждёт, пока звук не уйдёт дальше AHEAD_S вперёд, и шлёт кадр. False — пора прекращать."""
    while session.is_live(turn) and pacer.ahead() >= AHEAD_S:
        await asyncio.sleep(PACE_STEP_S)
    if not session.is_live(turn):
        return False
    try:
        await session.send_bytes(piece)
    except ConnectionError:
        return False
    pacer.add(len(piece))
    return True
