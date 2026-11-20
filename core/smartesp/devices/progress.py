"""Ход ответа на колонке: сколько звука отправлено и сколько уже прозвучало."""

from __future__ import annotations

from collections.abc import Callable

from smartesp.contracts import SAMPLE_RATE

BYTES_PER_S = SAMPLE_RATE * 2  # s16le, моно


class ReplyProgress:
    """Звук ответа хода хаба turn_id: отправлено (sent) и доиграно по событиям played.

    Колонка без played (протокол < 3 или прошивка до 0.4.0) — доиграно по оценке темпа:
    отправлено минус то, что колонке ещё играть (ahead(), секунды).
    """

    def __init__(self, turn_id: int, ahead: Callable[[], float]) -> None:
        self.turn_id = turn_id
        self.sent = 0  # байт звука, отданных колонке
        self.played: int | None = None  # байт, доигранных по последнему played; None — событий не было
        self._ahead = ahead

    def position(self) -> int:
        """Сколько байт ответа уже прозвучало (не больше отправленного)."""
        if self.played is not None:
            return min(self.played, self.sent)
        return max(self.sent - round(max(self._ahead(), 0.0) * BYTES_PER_S), 0)
