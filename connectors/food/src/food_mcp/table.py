"""Встроенная таблица частых продуктов на 100 г (файл `foods.tsv` рядом)."""

from dataclasses import dataclass
from functools import cache
from importlib import resources

from .food import Food


@dataclass(frozen=True)
class TableFood:
    """Продукт таблицы и все его названия (основное и синонимы)."""

    food: Food
    keys: tuple[str, ...]


def _parse_line(line: str) -> TableFood:
    # Пустая колонка синонимов в конце строки может быть срезана редактором.
    parts = line.rstrip("\n").split("\t")
    name, kcal, protein, fat, carbs, piece, synonyms = (parts + [""])[:7]
    food = Food(
        name=name,
        kcal_100g=float(kcal),
        protein=float(protein),
        fat=float(fat),
        carbs=float(carbs),
        piece_grams=float(piece),
    )
    extra = tuple(s.strip() for s in synonyms.split(";") if s.strip())
    return TableFood(food, (name, *extra))


@cache
def table_foods() -> tuple[TableFood, ...]:
    """Все продукты таблицы по порядку файла."""
    text = resources.files(__package__).joinpath("foods.tsv").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    return tuple(_parse_line(line) for line in lines)
