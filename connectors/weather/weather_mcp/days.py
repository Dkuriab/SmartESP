"""Разбор названия дня: сегодня, завтра, послезавтра, день недели, выходные."""

from dataclasses import dataclass
from datetime import date

# (основа слова, фраза «в …», номер дня недели: понедельник = 0)
_WEEKDAYS = [
    ("понедельни", "в понедельник", 0),
    ("вторни", "во вторник", 1),
    ("сред", "в среду", 2),
    ("четверг", "в четверг", 3),
    ("пятни", "в пятницу", 4),
    ("суббот", "в субботу", 5),
    ("воскресень", "в воскресенье", 6),
]


@dataclass(frozen=True)
class Day:
    """Запрошенный день: смещения от сегодня в днях и подпись для ответа."""

    offsets: list[int]
    label: str


def parse_day(text: str, today: date) -> Day | None:
    """Разбирает день. День недели — ближайший, включая сегодня. Непонятное — None."""
    word = " ".join(text.lower().replace("ё", "е").split())
    for prefix in ("в ", "во ", "на "):
        if word.startswith(prefix):
            word = word.removeprefix(prefix)
            break
    fixed = {"": 0, "сегодня": 0, "завтра": 1, "послезавтра": 2}
    if word in fixed:
        offset = fixed[word]
        return Day([offset], ["сегодня", "завтра", "послезавтра"][offset])
    if word in ("выходные", "выходных", "выходной"):
        saturday = (5 - today.weekday()) % 7
        if today.weekday() == 6:
            return Day([0], "в выходные")
        return Day([saturday, saturday + 1] if today.weekday() != 5 else [0, 1], "в выходные")
    for stem, label, number in _WEEKDAYS:
        if word.startswith(stem):
            offset = (number - today.weekday()) % 7
            return Day([offset], "сегодня" if offset == 0 else label)
    return None
