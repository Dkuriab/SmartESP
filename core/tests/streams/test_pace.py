"""Журнал темпа живого потока: провалы (колонка недоиграла) и общая скорость колонки."""

import logging

import pytest

from smartesp.streams.pace import PaceLog

RATE = 48000
BYTES_S = RATE * 2


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_steady_live_stream_logs_only_summary(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    pace = PaceLog(clock, summary_every_s=60.0)
    caplog.set_level(logging.INFO, "smartesp.streams.pace")
    for second in range(62):
        clock.t = 100.0 + second
        pace.observe("aa", 7, RATE, live=True, played=second * BYTES_S)
    texts = [r.getMessage() for r in caplog.records]
    assert texts == ["Поток 7 на aa: за 60 с сыграно 100.0 % реального времени, провалов 0"]


def test_stall_is_logged_and_counted(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    pace = PaceLog(clock, summary_every_s=60.0)
    caplog.set_level(logging.INFO, "smartesp.streams.pace")
    pace.observe("aa", 7, RATE, live=True, played=0)
    clock.t += 1.0
    pace.observe("aa", 7, RATE, live=True, played=BYTES_S)
    clock.t += 1.0
    pace.observe("aa", 7, RATE, live=True, played=BYTES_S + BYTES_S // 2)  # полсекунды тишины
    assert [r.getMessage() for r in caplog.records] == [
        "Поток 7 на aa: буфер колонки опустел — сыграно 0.5 с за 1.0 с"
    ]
    assert pace.stalls("aa") == 1


def test_files_and_new_stream_reset(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    pace = PaceLog(clock, summary_every_s=60.0)
    caplog.set_level(logging.INFO, "smartesp.streams.pace")
    pace.observe("aa", 7, RATE, live=False, played=0)  # файл: колонка копит сколько хочет — не следим
    clock.t += 1.0
    pace.observe("aa", 7, RATE, live=False, played=0)
    pace.observe("aa", 8, RATE, live=True, played=0)
    clock.t += 1.0
    pace.observe("aa", 9, RATE, live=True, played=10)  # новый поток — счёт с нуля, не провал
    assert caplog.records == []
