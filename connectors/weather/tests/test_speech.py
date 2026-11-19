"""Тесты русских форм и разбора дня."""

from datetime import date

import pytest

from weather_mcp.days import parse_day
from weather_mcp.speech import (
    condition,
    degrees,
    meters_per_second,
    millimeters,
    percent,
    round_half_up,
)

# 2026-11-19 — четверг
TODAY = date(2026, 11, 19)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (-3, "минус 3 градуса"),
        (1, "1 градус"),
        (5, "5 градусов"),
        (0, "0 градусов"),
        (11, "11 градусов"),
        (21, "21 градус"),
        (-1, "минус 1 градус"),
        (22.4, "22 градуса"),
        (-0.4, "0 градусов"),
    ],
)
def test_degrees(value: float, text: str) -> None:
    assert degrees(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1, "1 метр в секунду"),
        (4, "4 метра в секунду"),
        (4.4, "4 метра в секунду"),
        (5, "5 метров в секунду"),
    ],
)
def test_wind(value: float, text: str) -> None:
    assert meters_per_second(value) == text


def test_condition_known_and_unknown() -> None:
    assert condition(0) == "ясно"
    assert condition(73) == "снег"
    assert condition(61) == "небольшой дождь"
    assert condition(999) == "без уточнений"


@pytest.mark.parametrize(
    ("text", "offsets", "label"),
    [
        ("сегодня", [0], "сегодня"),
        ("", [0], "сегодня"),
        ("Завтра", [1], "завтра"),
        ("послезавтра", [2], "послезавтра"),
        ("в пятницу", [1], "в пятницу"),
        ("понедельник", [4], "в понедельник"),
        ("во вторник", [5], "во вторник"),
        ("в среду", [6], "в среду"),
        ("четверг", [0], "сегодня"),
        ("в воскресенье", [3], "в воскресенье"),
        ("в выходные", [2, 3], "в выходные"),
        ("сегодня вечером", [0], "сегодня"),
        ("завтра утром", [1], "завтра"),
        ("на завтра днём", [1], "завтра"),
    ],
)
def test_parse_day(text: str, offsets: list[int], label: str) -> None:
    parsed = parse_day(text, TODAY)
    assert parsed is not None
    assert parsed.offsets == offsets
    assert parsed.label == label


def test_parse_day_unknown() -> None:
    assert parse_day("средний", TODAY) is None
    assert parse_day("когда-нибудь", TODAY) is None


def test_weekend_on_sunday() -> None:
    parsed = parse_day("в выходные", date(2026, 11, 22))
    assert parsed is not None
    assert parsed.offsets == [0]


def test_genitive_after_to() -> None:
    assert degrees(1, after_to=True) == "1 градуса"
    assert degrees(4, after_to=True) == "4 градусов"
    assert degrees(-1, after_to=True) == "минус 1 градуса"
    assert meters_per_second(3, after_to=True) == "3 метров в секунду"
    assert meters_per_second(1, after_to=True) == "1 метра в секунду"


def test_round_half_up() -> None:
    assert [round_half_up(x) for x in (2.5, 0.5, -0.5, -2.5, 2.4, -7.5)] == [3, 1, 0, -2, 2, -7]
    assert degrees(2.5) == "3 градуса"
    assert degrees(-2.5) == "минус 2 градуса"


def test_millimeters_and_percent() -> None:
    assert millimeters(2.5) == "2,5 миллиметра"
    assert millimeters(1) == "1 миллиметр"
    assert millimeters(5) == "5 миллиметров"
    assert millimeters(0.3) == "0,3 миллиметра"
    assert percent(1) == "1 процент"
    assert percent(21) == "21 процент"
    assert percent(60) == "60 процентов"
    assert percent(3) == "3 процента"
