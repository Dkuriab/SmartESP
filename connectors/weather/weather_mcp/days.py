"""Разбор названия дня: сегодня, завтра, послезавтра, день недели, выходные."""

from dataclasses import dataclass
from datetime import date

# номер дня недели (понедельник = 0) -> (формы слова, фраза «в …»)
_WEEKDAYS: list[tuple[tuple[str, ...], str]] = [
    (("понедельник", "понедельника"), "в понедельник"),
    (("вторник", "вторника"), "во вторник"),
    (("среда", "среду", "среды"), "в среду"),
    (("четверг", "четверга"), "в четверг"),
    (("пятница", "пятницу", "пятницы"), "в пятницу"),
    (("суббота", "субботу", "субботы"), "в субботу"),
    (("воскресенье", "воскресенья"), "в воскресенье"),
]
_FILLERS = {"в", "во", "на"}
# часть суток принимаем, но отвечаем на весь день
_PARTS_OF_DAY = {"утром", "днем", "вечером", "ночью"}
_FIXED = {"": 0, "сегодня": 0, "завтра": 1, "послезавтра": 2}


@dataclass(frozen=True)
class Day:
    """Запрошенный день: смещения от сегодня в днях и подпись для ответа."""

    offsets: list[int]
    label: str


def weekday_label(number: int) -> str:
    """Фраза «в среду» для номера дня недели."""
    return _WEEKDAYS[number][1]


def _weekend(today: date) -> Day:
    weekday = today.weekday()
    if weekday == 6:
        return Day([0], "в выходные")
    saturday = 0 if weekday == 5 else 5 - weekday
    return Day([saturday, saturday + 1], "в выходные")


def parse_day(text: str, today: date) -> Day | None:
    """Разбирает день; лишние слова («вечером», «на») пропускает. Непонятное — None."""
    words = [w for w in text.lower().replace("ё", "е").split() if w not in _FILLERS]
    words = [w for w in words if w not in _PARTS_OF_DAY]
    if len(words) > 1:
        return None
    word = words[0] if words else ""
    if word in _FIXED:
        offset = _FIXED[word]
        return Day([offset], ["сегодня", "завтра", "послезавтра"][offset])
    if word in ("выходные", "выходных", "выходной"):
        return _weekend(today)
    for number, (forms, label) in enumerate(_WEEKDAYS):
        if word in forms:
            offset = (number - today.weekday()) % 7
            return Day([offset], "сегодня" if offset == 0 else label)
    return None
