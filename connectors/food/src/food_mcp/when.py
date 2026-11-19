"""Время еды из слов: «вчера», «8:30», «вчера в 19:30», ISO-дата."""

import re
from datetime import datetime, time, timedelta

_DAYS_BACK = {"": 0, "сейчас": 0, "сегодня": 0, "вчера": 1, "позавчера": 2}
_CLOCK = re.compile(r"(?:в\s+)?(\d{1,2})[:.](\d{2})$")
_NOON = time(12, 0)
_SLACK = timedelta(hours=1)  # часы Mac и «примерно сейчас»


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


def _bare_clock(clock: time, now: datetime) -> datetime:
    """Время без дня: позже «сейчас» больше чем на час — это вчера; чуть позже — «сейчас»."""
    moment = datetime.combine(now.date(), clock)
    if moment - now > _SLACK:
        moment -= timedelta(days=1)
    return min(moment, now)


def _day_clock(days_back: int, clock: time, now: datetime) -> datetime | None:
    """«Вчера в 19:30»: в будущем больше чем на час — не понято; чуть позже — «сейчас»."""
    moment = datetime.combine(now.date() - timedelta(days=days_back), clock)
    if moment - now > _SLACK:
        return None
    return min(moment, now)


def parse_when(text: str, now: datetime) -> datetime | None:
    """Время еды по словам; пусто — сейчас. Не понято — None. В будущем записей не бывает."""
    clean = " ".join(text.lower().split())
    if clean in _DAYS_BACK:
        return now - timedelta(days=_DAYS_BACK[clean])
    day_word, _, rest = clean.partition(" ")
    if day_word in _DAYS_BACK and rest:
        clock = _clock(rest)
        return None if clock is None else _day_clock(_DAYS_BACK[day_word], clock, now)
    clock = _clock(clean)
    if clock is not None:
        return _bare_clock(clock, now)
    return _iso(clean.upper().replace(" ", "T") if "-" in clean else clean, now)
