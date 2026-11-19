"""Тесты разбора времени еды."""

from datetime import datetime

import pytest

from food_mcp.when import parse_when

from .conftest import NOW


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", NOW),
        ("  ", NOW),
        ("сейчас", NOW),
        ("сегодня", NOW),
        ("Вчера", datetime(2026, 11, 18, 10, 32)),
        ("позавчера", datetime(2026, 11, 17, 10, 32)),
        ("08:15", datetime(2026, 11, 19, 8, 15)),
        ("8.15", datetime(2026, 11, 19, 8, 15)),
        ("вчера 19:30", datetime(2026, 11, 18, 19, 30)),
        ("вчера в 19:30", datetime(2026, 11, 18, 19, 30)),
        ("2026-11-10", datetime(2026, 11, 10, 12, 0)),
        ("2026-11-10T07:05", datetime(2026, 11, 10, 7, 5)),
    ],
)
def test_parse_when(text: str, expected: datetime) -> None:
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["завтра", "25:00", "когда-то", "2026-13-01", "2026-12-01"])
def test_parse_when_rejects(text: str) -> None:
    assert parse_when(text, NOW) is None
