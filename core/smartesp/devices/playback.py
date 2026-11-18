"""Отправка ответа на колонку: reply_start → звук кусками с темпом → reply_end."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator

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
    """Модель воспроизведения на колонке: когда она доиграет всё отправленное.

    Если звук кончился раньше, чем пришёл следующий кусок (колонка молчала),
    пропущенное время не даёт «кредита»: новый звук начинает играть сейчас.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._play_end = clock()  # момент (по clock), когда колонка доиграет отправленное

    def ahead(self) -> float:
        """Сколько секунд отправленного звука колонке ещё играть."""
        return self._play_end - self._clock()

    def add(self, size: int) -> None:
        """Учитывает отправленный кадр размером size байт."""
        self._play_end = max(self._play_end, self._clock()) + size / BYTES_PER_S


async def send_reply(
    session: Session, turn_id: int, audio: AsyncIterator[bytes], clock: Callable[[], float]
) -> None:
    """Шлёт ответ хода turn_id. Ход закончился или связь оборвалась — тихо выходит без reply_end.

    Ошибки самого источника звука (audio) не глотаются — они уходят вызывающему.
    При досрочном выходе у audio вызывается aclose(), если он есть.
    """
    active = session.active
    if active is None or not session.is_live(turn_id):
        return
    if not await session.send(reply_start(active.esp_turn), turn_id):
        return
    pacer = _Pacer(clock)
    try:
        async for chunk in audio:
            for piece in _pieces(chunk):
                if not await _send_piece(session, turn_id, piece, pacer):
                    return
    finally:
        await _close_audio(audio)
    await session.send(reply_end(active.esp_turn), turn_id)


async def _send_piece(session: Session, turn_id: int, piece: bytes, pacer: _Pacer) -> bool:
    """Ждёт, пока звук впереди не станет меньше AHEAD_S, и шлёт кадр. False — пора прекращать."""
    while session.is_live(turn_id) and pacer.ahead() >= AHEAD_S:
        await asyncio.sleep(PACE_STEP_S)
    if not await session.send(piece, turn_id):
        return False
    pacer.add(len(piece))
    return True


async def _close_audio(audio: AsyncIterator[bytes]) -> None:
    """Закрывает источник звука, если это асинхронный генератор."""
    if isinstance(audio, AsyncGenerator):
        await audio.aclose()
