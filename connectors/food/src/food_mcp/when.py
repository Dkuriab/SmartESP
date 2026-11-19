"""Время еды из слов: «вчера», «8:30», «вчера в 19:30», ISO-дата."""

import re
from datetime import datetime, time, timedelta

_DAYS_BACK = {"": 0, "сейчас": 0, "сегодня": 0, "вчера": 1, "позавчера": 2}
_CLOCK = re.compile(r"(?:в\s+)?(\d{1,2})[:.](\d{2})$")
_NOON = time(12, 0)


def _clock(text: str) -> time | None:
    found = _CLOCK.fullmatch(text)
    if not found:
        return None
    hour, minute = int(found.group(1)), int(found.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _iso(text: str, now: datetime) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None
    if "T" not in text:
        parsed = datetime.combine(parsed.date(), _NOON)
    return parsed if parsed <= now else None


def parse_when(text: str, now: datetime) -> datetime | None:
    """Время еды по словам; пусто — сейчас. Не понято или в будущем по дате — None."""
    clean = " ".join(text.lower().split())
    if clean in _DAYS_BACK:
        return now - timedelta(days=_DAYS_BACK[clean])
    day_word, _, rest = clean.partition(" ")
    if day_word in _DAYS_BACK and rest:
        clock = _clock(rest)
        if clock is None:
            return None
        return datetime.combine(now.date() - timedelta(days=_DAYS_BACK[day_word]), clock)
    clock = _clock(clean)
    if clock is not None:
        return datetime.combine(now.date(), clock)
    return _iso(clean.upper().replace(" ", "T") if "-" in clean else clean, now)
