"""Название из справочника штрихкодов → вес упаковки и подходящие продукты (только предложение)."""

import re
from dataclasses import dataclass
from pathlib import Path

from . import products
from .food import Food
from .names import tokens
from .table import table_foods

MAX_PACK = 50_000
_PACK = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг|л|мл|гр|г)(?![a-zа-я])", re.I)
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_MAX_OPTIONS = 3


def pack_grams(name: str) -> float:
    """Вес упаковки из названия («0,950л» → 950, «95гр» → 95; мл и л — как граммы); нет — 0."""
    found = _PACK.search(name)
    if not found:
        return 0.0
    grams = float(found.group(1).replace(",", ".")) * (1000 if found.group(2).lower() in ("кг", "л") else 1)
    return grams if 0 < grams <= MAX_PACK else 0.0


def _percents(text: str) -> set[str]:
    return {p.replace(",", ".") for p in _PERCENT.findall(text)}


@dataclass(frozen=True)
class Candidate:
    """Продукт, на который похоже название; `own` — из своей базы."""

    food: Food
    own: bool


def candidates(root: Path, name: str) -> list[Candidate]:
    """Продукты, все слова названия которых есть в названии товара. Только предложение.

    Выигрывают совпадения с наибольшим числом слов («кефир 1%» лучше «кефир»). Если в
    названии товара есть процент жирности, а у продукта другой — не подходит.
    """
    have = tokens(name)
    wanted = _percents(name)
    scored: list[tuple[int, Candidate]] = []
    for food, _ in products.load(root):
        key = tokens(food.name)
        if key and key <= have:
            scored.append((len(key), Candidate(food, True)))
    for item in table_foods():
        fits = [len(tokens(k)) for k in item.keys if tokens(k) <= have and tokens(k)]
        own_percents = set().union(*(_percents(k) for k in item.keys))
        if fits and not (wanted and own_percents and not wanted & own_percents):
            scored.append((max(fits), Candidate(item.food, False)))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    unique = {c.food.name: c for s, c in scored if s == best}
    return list(unique.values())[:_MAX_OPTIONS]
