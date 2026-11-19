"""Слова для озвучки: длительности и время."""

from datetime import datetime, timedelta

import pytest

from tests.conftest import START, TZ
from timers_mcp.phrases import clock_time, duration, when_text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (1200, "20 минут"),
        (60, "1 минута"),
        (120, "2 минуты"),
        (21 * 60, "21 минута"),
        (750, "12 минут 30 секунд"),
        (30, "30 секунд"),
        (1, "1 секунда"),
        (3600, "1 час"),
        (5400, "1 час 30 минут"),
        (2 * 3600 + 59, "2 часа"),
        (0.2, "1 секунда"),
    ],
)
def test_duration_nominative(seconds: float, text: str) -> None:
    assert duration(seconds) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (60, "1 минуту"),
        (90, "1 минуту 30 секунд"),
        (1, "1 секунду"),
        (300, "5 минут"),
        (22 * 60, "22 минуты"),
    ],
)
def test_duration_accusative(seconds: float, text: str) -> None:
    assert duration(seconds, accusative=True) == text


def test_clock_time_in_local_zone() -> None:
    utc = datetime(2026, 11, 19, 4, 5, tzinfo=TZ).astimezone(tz=None)
    assert clock_time(utc, TZ) == "04:05"


def test_when_text() -> None:
    assert when_text(START.replace(hour=18, minute=30), START) == "в 18:30"
    assert when_text(START + timedelta(days=1), START) == "завтра в 14:00"
    assert when_text(START + timedelta(days=3), START) == "22.11 в 14:00"
