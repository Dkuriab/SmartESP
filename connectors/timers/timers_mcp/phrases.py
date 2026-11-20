"""Русские фразы для озвучки: длительности, время, ответы инструментов."""

import math
from datetime import datetime, timedelta, tzinfo

from timers_mcp.entry import Entry

DEFAULT_NAME = "таймер"

# Формы слов: (одна, две-четыре, пять и больше); у минут и секунд винительный отличается.
_HOUR = ("час", "часа", "часов")
_MINUTE = ("минута", "минуты", "минут")
_MINUTE_ACC = ("минуту", "минуты", "минут")
_SECOND = ("секунда", "секунды", "секунд")
_SECOND_ACC = ("секунду", "секунды", "секунд")


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Число со словом в нужной форме: 1 минута, 2 минуты, 5 минут."""
    tail = n % 100
    if 11 <= tail <= 14:
        form = forms[2]
    elif tail % 10 == 1:
        form = forms[0]
    elif 2 <= tail % 10 <= 4:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n} {form}"


def duration(seconds: float, accusative: bool = False) -> str:
    """Длительность словами («12 минут 30 секунд»); от часа секунды не называются.

    `accusative` — форма после «на»: «на 1 минуту». Дробные секунды округляются вверх.
    """
    total = max(1, math.ceil(seconds - 1e-9))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    minute_forms = _MINUTE_ACC if accusative else _MINUTE
    second_forms = _SECOND_ACC if accusative else _SECOND
    if hours:
        parts = [plural(hours, _HOUR)] + ([plural(minutes, minute_forms)] if minutes else [])
    else:
        parts = [plural(n, f) for n, f in ((minutes, minute_forms), (secs, second_forms)) if n]
    return " ".join(parts)


def clock_time(moment: datetime, zone: tzinfo | None) -> str:
    """Время «ЧЧ:ММ» в часовом поясе `zone`."""
    return moment.astimezone(zone).strftime("%H:%M")


def when_text(due: datetime, now: datetime) -> str:
    """Когда сработает: «в 18:30», «завтра в 07:00», «22.11 в 09:00»."""
    local = due.astimezone(now.tzinfo)
    at = f"в {local:%H:%M}"
    if local.date() == now.date():
        return at
    if local.date() == now.date() + timedelta(days=1):
        return f"завтра {at}"
    return f"{local:%d.%m} {at}"


def _timer_title(name: str) -> str:
    """«Таймер «картошка»», а таймер с именем по умолчанию — просто «Таймер»."""
    return "Таймер" if name == DEFAULT_NAME else f"Таймер «{name}»"


def task_title(entry: Entry) -> str:
    """Название задачи «В работе»: «Таймер «картошка»», «Напоминание: позвонить маме»."""
    return _timer_title(entry.name) if entry.kind == "timer" else f"Напоминание: {entry.name}"


def started_text(entry: Entry, seconds: float) -> str:
    """Ответ на постановку таймера."""
    return f"{_timer_title(entry.name)} на {duration(seconds, accusative=True)}."


def reminder_set_text(entry: Entry, now: datetime) -> str:
    """Ответ на постановку напоминания."""
    return f"Напомню {when_text(entry.due, now)}: {entry.name}."


def fired_text(entry: Entry) -> str:
    """Что сказать, когда таймер или напоминание сработали."""
    if entry.kind == "timer":
        return f"{_timer_title(entry.name)}: время вышло."
    return f"Напоминание: {entry.name}."


def missed_text(entry: Entry, zone: tzinfo | None) -> str:
    """Что сказать о сработавшем, пока коннектор не работал."""
    at = clock_time(entry.due, zone)
    if entry.kind == "timer":
        title = "Пропущен таймер" if entry.name == DEFAULT_NAME else f"Пропущен таймер «{entry.name}»"
        return f"{title} (сработал в {at})."
    return f"Пропущено напоминание «{entry.name}» (сработало в {at})."


def list_text(entries: list[Entry], now: datetime) -> str:
    """Что идёт и сколько осталось."""
    if not entries:
        return "Таймеров и напоминаний нет."
    parts: list[str] = []
    for entry in entries:
        if entry.kind == "timer":
            parts.append(f"{entry.name} — {duration((entry.due - now).total_seconds())}")
        else:
            parts.append(f"напоминание «{entry.name}» — {when_text(entry.due, now)}")
    return "; ".join(parts) + "."


def cancelled_text(name: str, removed: list[Entry], everything: bool) -> str:
    """Ответ на отмену."""
    if everything:
        return f"Отменено: {len(removed)}." if removed else "Отменять нечего."
    if not removed:
        return f"Таймера или напоминания «{name}» нет."
    entry = removed[0]
    if entry.kind == "timer":
        return f"{_timer_title(entry.name)} отменён."
    return f"Напоминание «{entry.name}» отменено."
