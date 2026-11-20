"""Обработчик «время»: к каждой фразе справка с местными датой и временем.

У модели нет часов, и без справки она выдумывает время. Это общий контекст,
а не инструмент: маленькая модель вызывала бы «который час» ненадёжно. Пометка —
справочная (reference): модель видит её как данные для инструментов и прямых
вопросов и не вставляет время в обычные ответы. Части суток («вечер») в ней нет:
это слово модель охотнее всего переносила в ответы («в этот вечер»).
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


def describe(moment: datetime) -> str:
    """«среда, 19 ноября 2026, 21:40»."""
    date = f"{_WEEKDAYS[moment.weekday()]}, {moment.day} {_MONTHS[moment.month - 1]} {moment.year}"
    return f"{date}, {moment:%H:%M}"


class Clock:
    """Добавляет к фразе справку с местным временем."""

    name = "clock"
    prompt_hint = ""  # справка объясняет себя сама (conversation/prompt.py)

    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        """now — часы (в тестах подменяются); по умолчанию местное время."""
        self._now = now

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Одна справочная пометка «время — …»."""
        text = describe(self._now())
        return [Annotation(text=text, source=self.name, label=LABEL, reference=True)]
