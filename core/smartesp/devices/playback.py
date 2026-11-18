"""Отправка ответа на колонку: reply_start → звук кусками с темпом → reply_end."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator

from smartesp.contracts import SAMPLE_RATE

from .messages import reply_end, reply_start
from .session import Session

CHUNK_BYTES = 4096  # размер звукового кадра к колонке
AHEAD_S = 10.0  # не больше стольких секунд звука впереди воспроизведения
BURST_S = 1.0  # пока впереди меньше стольких секунд звука, шлём со скоростью сети
BURST_RATE = 4.0  # дальше — не быстрее стольких секунд звука в секунду (сетевой буфер колонки — 2 с)
PACE_STEP_S = 0.05  # как часто проверять темп и жив ли ход, пока ждём (не реже)
PACE_MIN_S = 0.002  # самый короткий сон между проверками темпа
BYTES_PER_S = SAMPLE_RATE * 2  # s16le, моно


def _pieces(chunk: bytes) -> Iterator[bytes]:
    """Режет кусок на кадры не длиннее CHUNK_BYTES."""
    for start in range(0, len(chunk), CHUNK_BYTES):
        yield chunk[start : start + CHUNK_BYTES]


class _Pacer:
    """Модель воспроизведения на колонке и темп отправки.

    Первую ~BURST_S секунду звука шлём сразу, дальше — не быстрее BURST_RATE× реального
    времени (колонка не успевает перекладывать звук из сетевого буфера, лишнее
    выбрасывает), а когда впереди AHEAD_S секунд — со скоростью воспроизведения.
    Если звук кончился раньше, чем пришёл следующий кусок (колонка молчала),
    пропущенное время не даёт «кредита»: новый звук начинает играть сейчас.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._play_end = clock()  # момент (по clock), когда колонка доиграет отправленное
        self._next_send = clock()  # раньше этого момента не слать, если впереди уже ≥ BURST_S

    def ahead(self) -> float:
        """Сколько секунд отправленного звука колонке ещё играть."""
        return self._play_end - self._clock()

    def ready(self) -> bool:
        """True, если следующий кадр можно слать сейчас."""
        now = self._clock()
        ahead = self._play_end - now
        if ahead >= AHEAD_S:
            return False
        return ahead < BURST_S or now >= self._next_send

    def wait_s(self) -> float:
        """Сколько секунд (по clock) примерно ждать до готовности; 0 — уже пора проверить."""
        now = self._clock()
        return max(self._play_end - now - AHEAD_S, self._next_send - now, 0.0)

    def add(self, size: int) -> None:
        """Учитывает отправленный кадр размером size байт."""
        now = self._clock()
        duration = size / BYTES_PER_S
        self._play_end = max(self._play_end, now) + duration
        if self._play_end - now > BURST_S:
            self._next_send = max(self._next_send, now) + duration / BURST_RATE


async def send_reply(
    session: Session, turn_id: int, audio: AsyncIterator[bytes], clock: Callable[[], float]
) -> None:
    """Шлёт ответ хода turn_id. Ход закончился или связь оборвалась — тихо выходит без reply_end.

    Ошибки самого источника звука (audio) не глотаются — они уходят вызывающему.
    При любом выходе (и когда ход уже неактивен) у audio вызывается aclose(), если он есть.
    """
    try:
        active = session.active
        if active is None or not session.is_live(turn_id):
            return
        if not await session.send(reply_start(active.esp_turn), turn_id):
            return
        pacer = _Pacer(clock)
        async for chunk in audio:
            for piece in _pieces(chunk):
                if not await _send_piece(session, turn_id, piece, pacer):
                    return
    finally:
        await _close_audio(audio)
    await session.send(reply_end(active.esp_turn), turn_id)


async def _send_piece(session: Session, turn_id: int, piece: bytes, pacer: _Pacer) -> bool:
    """Ждёт, пока темп позволит (см. _Pacer), и шлёт кадр. False — пора прекращать."""
    while session.is_live(turn_id) and not pacer.ready():
        await asyncio.sleep(min(max(pacer.wait_s(), PACE_MIN_S), PACE_STEP_S))
    if not await session.send(piece, turn_id):
        return False
    pacer.add(len(piece))
    return True


async def _close_audio(audio: AsyncIterator[bytes]) -> None:
    """Закрывает источник звука, если это асинхронный генератор."""
    if isinstance(audio, AsyncGenerator):
        await audio.aclose()
