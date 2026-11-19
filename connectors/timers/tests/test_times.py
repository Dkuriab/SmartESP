"""Разбор времени напоминания."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import START, TZ
from timers_mcp.times import parse_reminder_time


def local(naive: datetime) -> datetime:
    return naive.replace(tzinfo=TZ)


def test_hh_mm_later_today() -> None:
    assert parse_reminder_time("18:30", START, local) == START.replace(hour=18, minute=30)


def test_hh_mm_passed_means_tomorrow() -> None:
    due = parse_reminder_time("7:05", START, local)
    assert due == START.replace(hour=7, minute=5) + timedelta(days=1)


def test_hh_mm_equal_to_now_means_tomorrow() -> None:
    assert parse_reminder_time("14:00", START, local) == START + timedelta(days=1)


def test_iso_with_zone() -> None:
    assert parse_reminder_time("2026-11-20T09:00:00+03:00", START, local) == START.replace(day=20, hour=9)


def test_iso_naive_is_local() -> None:
    assert parse_reminder_time("2026-11-20T09:00", START, local) == START.replace(day=20, hour=9)


def test_iso_in_past_is_error() -> None:
    with pytest.raises(ValueError, match="прошло"):
        parse_reminder_time("2026-11-18T09:00", START, local)


@pytest.mark.parametrize("text", ["25:00", "12:61", "завтра", "", "12"])
def test_bad_time(text: str) -> None:
    with pytest.raises(ValueError, match="ЧЧ:ММ"):
        parse_reminder_time(text, START, local)


def test_dst_switch_uses_offset_of_target_day() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 10, 24, 12, 0, tzinfo=berlin)  # летнее время, +2

    def berlin_local(naive: datetime) -> datetime:
        return naive.replace(tzinfo=berlin)

    due = parse_reminder_time("18:00", now, berlin_local)
    assert (due.day, due.utcoffset()) == (24, timedelta(hours=2))
    due = parse_reminder_time("07:00", now, berlin_local)  # завтра, уже зимнее время, +1
    assert (due.day, due.hour, due.utcoffset()) == (25, 7, timedelta(hours=1))
    due = parse_reminder_time("07:00", datetime(2026, 10, 25, 1, 0, tzinfo=berlin), berlin_local)
    assert (due.day, due.hour, due.utcoffset()) == (25, 7, timedelta(hours=1))
