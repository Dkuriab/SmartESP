"""Разбор времени напоминания: «ЧЧ:ММ» или ISO, местное время."""

import re
from collections.abc import Callable
from datetime import datetime, timedelta

_HH_MM = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")
_BAD_FORMAT = "Не понял время. Нужно «ЧЧ:ММ», например 18:30, или дата и время ISO."

Localize = Callable[[datetime], datetime]


def parse_reminder_time(text: str, now: datetime, local: Localize) -> datetime:
    """Когда напомнить.

    «ЧЧ:ММ» — сегодня, а если это время уже прошло (или наступает сейчас) — завтра.
    ISO («2026-11-20T09:00», можно с поясом) — как есть; без пояса — местное время.
    `local` переводит местное время без пояса в время с поясом (с учётом летнего).
    Возвращает время с часовым поясом; непонятное или прошедшее время — ValueError
    с русским текстом для человека.
    """
    match = _HH_MM.match(text)
    if match:
        return _today_or_tomorrow(int(match.group(1)), int(match.group(2)), now, local)
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(_BAD_FORMAT) from None
    if moment.tzinfo is None:
        moment = local(moment)
    if moment <= now:
        raise ValueError("Это время уже прошло.")
    return moment


def _today_or_tomorrow(hour: int, minute: int, now: datetime, local: Localize) -> datetime:
    """Ближайшие ЧЧ:ММ после `now` по местным часам."""
    if hour > 23 or minute > 59:
        raise ValueError(_BAD_FORMAT)
    moment = datetime(now.year, now.month, now.day, hour, minute)
    if local(moment) <= now:
        moment += timedelta(days=1)
    return local(moment)
