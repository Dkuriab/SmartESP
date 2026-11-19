"""Русские формы для озвучки: градусы, ветер, слова для кодов погоды WMO."""

_CONDITIONS: dict[int, str] = {
    0: "ясно",
    1: "в основном ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "сильная ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с сильным градом",
}


def condition(code: int) -> str:
    """Короткое русское слово для кода погоды WMO."""
    return _CONDITIONS.get(code, "без уточнений")


def _plural(number: int, one: str, few: str, many: str) -> str:
    """Форма слова по числу: 1 градус, 2 градуса, 5 градусов."""
    tail = abs(number) % 100
    if 11 <= tail <= 14:
        return many
    last = tail % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _genitive(number: int, one: str, many: str) -> str:
    """Форма после «до»: до 1 градуса, до 5 градусов, до 22 градусов."""
    return one if abs(number) % 100 != 11 and abs(number) % 10 == 1 else many


def degrees(value: float, after_to: bool = False) -> str:
    """Температура словами: «минус 3 градуса», «1 градус»; after_to — после «до»."""
    number = round(value)
    if after_to:
        word = _genitive(number, "градуса", "градусов")
    else:
        word = _plural(number, "градус", "градуса", "градусов")
    sign = "минус " if number < 0 else ""
    return f"{sign}{abs(number)} {word}"


def plain_number(value: float) -> str:
    """Целое число со знаком словом для диапазона: «минус 3», «2»."""
    number = round(value)
    return f"минус {abs(number)}" if number < 0 else str(number)


def meters_per_second(value: float, after_to: bool = False) -> str:
    """Скорость ветра: «4 метра в секунду»; after_to — после «до»."""
    number = round(value)
    if after_to:
        word = _genitive(number, "метра", "метров")
    else:
        word = _plural(number, "метр", "метра", "метров")
    return f"{number} {word} в секунду"
