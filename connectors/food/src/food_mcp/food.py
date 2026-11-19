"""Продукт: калорийность и Б/Ж/У на 100 г, вес упаковки и штуки."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Food:
    """Продукт с пищевой ценностью на 100 г.

    `pack_grams` — вес упаковки, `piece_grams` — вес одной штуки (0 — неизвестен).
    """

    name: str
    kcal_100g: float
    protein: float = 0.0
    fat: float = 0.0
    carbs: float = 0.0
    barcode: str = ""
    pack_grams: float = 0.0
    piece_grams: float = 0.0

    @property
    def unit_grams(self) -> float:
        """Вес одной «штуки» для счёта: штука, иначе упаковка (0 — не считается штуками)."""
        return self.piece_grams or self.pack_grams

    def to_dict(self) -> dict[str, Any]:
        """Словарь для JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Food":
        """Продукт из словаря JSON (лишние поля игнорируются)."""
        return cls(
            name=str(raw.get("name", "")),
            kcal_100g=float(raw.get("kcal_100g", 0)),
            protein=float(raw.get("protein", 0)),
            fat=float(raw.get("fat", 0)),
            carbs=float(raw.get("carbs", 0)),
            barcode=str(raw.get("barcode", "")),
            pack_grams=float(raw.get("pack_grams", 0)),
            piece_grams=float(raw.get("piece_grams", 0)),
        )
