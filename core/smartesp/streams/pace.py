"""Темп колонки на живом потоке (звук Mac, радио) по отчётам stream_status — только для журнала.

Живой поток приходит ровно в реальном времени, поэтому буфер колонки держит лишь то, что она
накопила перед стартом. Опустел буфер — колонка молчит, пока копит снова, и сыгранное отстаёт
от прошедшего времени: это «провал». Общая скорость за долгое время показывает, расходятся ли
часы колонки и источника (больше 100 % — колонка играет быстрее, буфер постепенно тает).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

_log = logging.getLogger(__name__)

STALL_SHARE = 0.7  # сыграно меньше этой доли прошедшего времени — провал
MIN_GAP_S = 0.5  # отчёты чаще — не судим: время прихода по Wi-Fi пляшет
SUMMARY_EVERY_S = 60.0


@dataclass
class _Pace:
    stream: int
    first_t: float
    first_played: int
    last_t: float
    last_played: int
    summary_t: float
    stalls: int = 0


class PaceLog:
    """Следит за живыми потоками колонок; clock — монотонные секунды."""

    def __init__(self, clock: Callable[[], float], summary_every_s: float = SUMMARY_EVERY_S) -> None:
        self._clock = clock
        self._summary_every_s = summary_every_s
        self._paces: dict[str, _Pace] = {}

    def observe(self, device_id: str, stream: int, rate: int, *, live: bool, played: int) -> None:
        """Отчёт playing колонки device_id: поток stream, сыграно played байт s16le моно на rate."""
        now = self._clock()
        pace = self._paces.get(device_id)
        if not live:
            self._paces.pop(device_id, None)
            return
        if pace is None or pace.stream != stream or played < pace.last_played:
            self._paces[device_id] = _Pace(stream, now, played, now, played, now)
            return
        gap = now - pace.last_t
        if gap < MIN_GAP_S:
            return
        sounded = (played - pace.last_played) / (2 * rate)
        if sounded < STALL_SHARE * gap:
            pace.stalls += 1
            text = "Поток %d на %s: буфер колонки опустел — сыграно %.1f с за %.1f с"
            _log.info(text, stream, device_id, sounded, gap)
        pace.last_t, pace.last_played = now, played
        if now - pace.summary_t >= self._summary_every_s:
            pace.summary_t = now
            total = now - pace.first_t
            share = (played - pace.first_played) / (2 * rate) / total * 100
            _log.info(
                "Поток %d на %s: за %d с сыграно %.1f %% реального времени, провалов %d",
                stream, device_id, round(total), share, pace.stalls,
            )  # fmt: skip

    def stalls(self, device_id: str) -> int:
        """Сколько провалов у текущего живого потока колонки (для тестов и состояния)."""
        pace = self._paces.get(device_id)
        return pace.stalls if pace is not None else 0
