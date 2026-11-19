"""Своя база продуктов: `products.json` в папке человека (свои продукты и кэш Open Food Facts)."""

import json
from pathlib import Path
from typing import Any

from .food import Food
from .names import tokens
from .off import barcode_key
from .storage import read_text, write_atomic

FILE = "products.json"


def _path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> list[tuple[Food, str]]:
    """Продукты базы с источником («own» — свой, «off» — из Open Food Facts)."""
    text = read_text(_path(root))
    raw: list[dict[str, Any]] = json.loads(text) if text.strip() else []
    return [(Food.from_dict(item), str(item.get("source", "own"))) for item in raw]


def _save(root: Path, items: list[tuple[Food, str]]) -> None:
    data = [{**food.to_dict(), "source": source} for food, source in items]
    write_atomic(_path(root), json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def by_barcode(root: Path, code: str) -> Food | None:
    """Продукт с этим штрихкодом (UPC-A и EAN-13 с ведущим 0 — один код)."""
    key = barcode_key(code)
    for food, _ in load(root):
        if food.barcode and barcode_key(food.barcode) == key:
            return food
    return None


def _same(a: Food, b: Food) -> bool:
    if a.barcode and b.barcode:
        return barcode_key(a.barcode) == barcode_key(b.barcode)
    return tokens(a.name) == tokens(b.name)


def upsert(root: Path, food: Food, source: str) -> bool:
    """Добавляет продукт или заменяет такой же (по штрихкоду, иначе по названию).

    Возвращает True, если продукт заменён.
    """
    items = load(root)
    for i, (old, _) in enumerate(items):
        if _same(old, food):
            items[i] = (food, source)
            _save(root, items)
            return True
    _save(root, [*items, (food, source)])
    return False
