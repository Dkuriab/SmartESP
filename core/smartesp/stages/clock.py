"""Обработчик «время»: к каждой фразе пометка с местным временем.

У модели нет часов, и без пометки она выдумывает время. Это общий контекст,
а не инструмент: маленькая модель вызывала бы «который час» ненадёжно.
"""

from collections.abc import Callable
from datetime import datetime

from smartesp.contracts import Annotation, Utterance

LABEL = "время"
_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
# (час, с которого начинается часть суток, название)
_PARTS = ((18, "вечер"), (12, "день"), (6, "утро"), (0, "ночь"))


def part_of_day(hour: int) -> str:
    """Часть суток: ночь 0–5, утро 6–11, день 12–17, вечер 18–23."""
    return next(name for start, name in _PARTS if hour >= start)


def describe(moment: datetime) -> str:
    """«среда, 19 ноября 2026, 21:40, вечер»."""
    date = f"{_WEEKDAYS[moment.weekday()]}, {moment.day} {_MONTHS[moment.month - 1]} {moment.year}"
    return f"{date}, {moment:%H:%M}, {part_of_day(moment.hour)}"


class Clock:
    """Добавляет к фразе пометку с местным временем."""

    name = "clock"
    prompt_hint = "Пометка [время] — текущие дата и время, пользуйся ей."

    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        """now — часы (в тестах подменяются); по умолчанию местное время."""
        self._now = now

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Одна пометка «[время] …»."""
        return [Annotation(text=describe(self._now()), source=self.name, label=LABEL)]
