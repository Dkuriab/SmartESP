"""Русские названия продуктов: нормализация, отбрасывание окончаний, количество в тексте."""

import re
from dataclasses import dataclass

# Окончания, которые отрезаются (длинные — первыми). Грубо, но «гречку» и «гречки» → «гречк».
_ENDINGS = sorted(
    "ями ами ого его ому ему ыми ими ой ей ий ый ая яя ое ее ую юю ом ем ам ям ах ях ов ев "
    "ы и а я у ю е о ь й".split(),
    key=len,
    reverse=True,
)
_MIN_STEM = 2
_WORD = re.compile(r"[a-zа-я0-9]+")

_NUMBER_WORDS = {
    "один": 1,
    "одна": 1,
    "одно": 1,
    "одну": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
}
_PIECE_WORDS = {"шт", "шт.", "штука", "штуки", "штук", "штуку"}
_GRAMS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|грамм|грамма|граммов)\.?(?=\s|$)")


def stem(word: str) -> str:
    """Отрезает одно окончание, если остаётся не меньше двух букв."""
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= _MIN_STEM:
            return word[: -len(ending)]
    return word


def tokens(text: str) -> frozenset[str]:
    """Набор основ слов: без регистра, «ё», знаков и однобуквенных слов («с», «и»)."""
    words = _WORD.findall(text.lower().replace("ё", "е"))
    return frozenset(stem(w) for w in words if len(w) > 1 or w.isdigit())


@dataclass(frozen=True)
class Amount:
    """Разобранный текст: название, штук (0 — не сказано), граммов (0 — не сказано)."""

    name: str
    count: int
    grams: float


def _count(words: list[str]) -> tuple[int, list[str]]:
    """Ведущее число («2», «два») и слово «штуки» после него."""
    if not words:
        return 0, words
    first = words[0].lower()
    count = int(first) if first.isdigit() else _NUMBER_WORDS.get(first, 0)
    if not count:
        return 0, words
    rest = words[1:]
    if rest and rest[0].lower() in _PIECE_WORDS:
        rest = rest[1:]
    return count, rest


def parse_amount(text: str) -> Amount:
    """Разбирает «2 яйца», «гречка 150 г», «200 гр творога» на название и количество."""
    grams = 0.0
    found = _GRAMS.search(text.lower())
    if found:
        grams = float(found.group(1).replace(",", "."))
        text = text[: found.start()] + text[found.end() :]
    count, words = _count(text.split())
    if grams:
        count = 0
    return Amount(" ".join(words), count, grams)
