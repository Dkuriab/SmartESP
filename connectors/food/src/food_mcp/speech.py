"""Числа и даты для озвучки: округление, десятичная запятая, склонение."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()


def round_half_up(value: float, digits: int = 0) -> Decimal:
    """Округление «как в школе» (514,5 → 515), без ошибок двоичных дробей."""
    exp = Decimal(1).scaleb(-digits)
    return Decimal(f"{value:.9f}").quantize(exp, rounding=ROUND_HALF_UP)


def kcal(value: float) -> str:
    """Калории — целым числом."""
    return str(round_half_up(value))


def num(value: float) -> str:
    """Граммы и Б/Ж/У — до десятых, с запятой, без «,0»."""
    text = str(round_half_up(value, 1))
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: 1 штука, 2 штуки, 5 штук."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def day_words(day: date) -> str:
    """«19 ноября»."""
    return f"{day.day} {_MONTHS[day.month - 1]}"
