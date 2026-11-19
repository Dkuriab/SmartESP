"""Open Food Facts: продукт по штрихкоду (сеть), проверка штрихкода."""

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .food import Food

API = "https://world.openfoodfacts.org/api/v2/product/"
FIELDS = "product_name,product_name_ru,brands,nutriments,quantity,product_quantity"
USER_AGENT = "SmartEsp-food/0.1 (home assistant)"
TIMEOUT_S = 5.0
_KJ_PER_KCAL = 4.184
_SEPARATORS = re.compile(r"[\s\-]")


def valid_barcode(raw: str) -> str | None:
    """Штрихкод из цифр (EAN-8, UPC-A, EAN-13) с верной контрольной цифрой; иначе None.

    Пробелы и дефисы убираются.
    """
    code = _SEPARATORS.sub("", raw)
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return None
    digits = [int(c) for c in code]
    body = reversed(digits[:-1])
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return code if (10 - total % 10) % 10 == digits[-1] else None


def barcode_key(code: str) -> str:
    """Ключ для сравнения: UPC-A (12 цифр) и он же в форме EAN-13 с ведущим 0 — один ключ."""
    return code[1:] if len(code) == 13 and code.startswith("0") else code


@dataclass(frozen=True)
class OffResult:
    """Ответ Open Food Facts.

    `status`: found — есть продукт с калорийностью (`food`); no_kcal — продукт есть, ккал нет
    (`name`); missing — нет такого штрихкода; offline — сеть или сервис недоступны.
    """

    status: Literal["found", "no_kcal", "missing", "offline"]
    food: Food | None = None
    name: str = ""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _name(product: dict[str, Any]) -> str:
    name = str(product.get("product_name_ru") or product.get("product_name") or "").strip()
    brand = str(product.get("brands") or "").split(",")[0].strip()
    if brand and brand.lower() not in name.lower():
        name = f"{name} {brand}".strip()
    return name


def _kcal(nutriments: dict[str, Any]) -> float:
    kcal = _number(nutriments.get("energy-kcal_100g"))
    if kcal:
        return kcal
    return round(_number(nutriments.get("energy_100g")) / _KJ_PER_KCAL, 1)


def parse_product(code: str, product: dict[str, Any]) -> OffResult:
    """Разбирает поле `product` ответа API v2."""
    raw_nutriments = product.get("nutriments")
    nutriments: dict[str, Any] = raw_nutriments if isinstance(raw_nutriments, dict) else {}
    name = _name(product) or f"продукт {code}"
    kcal = _kcal(nutriments)
    if kcal <= 0:
        return OffResult("no_kcal", name=name)
    food = Food(
        name=name,
        kcal_100g=kcal,
        protein=_number(nutriments.get("proteins_100g")),
        fat=_number(nutriments.get("fat_100g")),
        carbs=_number(nutriments.get("carbohydrates_100g")),
        barcode=code,
        pack_grams=_number(product.get("product_quantity")),
    )
    return OffResult("found", food=food)


class OpenFoodFacts:
    """Клиент Open Food Facts; `transport` подменяется в тестах (сеть не нужна)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def lookup(self, code: str) -> OffResult:
        """Продукт по проверенному штрихкоду; ошибки сети и сервиса — `offline`."""
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
            ) as client:
                response = await client.get(API + code, params={"fields": FIELDS})
            if response.status_code == 404:
                return OffResult("missing")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return OffResult("offline")
        if not isinstance(payload, dict) or payload.get("status") != 1:
            return OffResult("missing")
        product = payload.get("product")
        if not isinstance(product, dict):
            return OffResult("missing")
        return parse_product(code, product)
