"""Поиск калорийности по порядку: своя база → дневник → Open Food Facts → таблица."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from . import diary, products
from .food import Food
from .names import tokens
from .off import OffResult, OpenFoodFacts, valid_barcode
from .table import table_foods

MAX_OPTIONS = 4
NOTHING = "Что записать? Скажи продукт и вес."


@dataclass(frozen=True)
class Found:
    """Продукт нашёлся; `source` — откуда («own», «off», «diary», «table»), `note` — пояснение."""

    food: Food
    source: str
    note: str = ""


@dataclass(frozen=True)
class Reply:
    """Не нашлось или неоднозначно: ответ человеку, запись не делается."""

    text: str


def bad_barcode(raw: str, tail: str = "проверь цифры.") -> str:
    return f"Штрихкод «{raw.strip()}» не похож на настоящий — {tail}"


def _ask(foods: list[Food]) -> Reply:
    names = list(dict.fromkeys(f.name for f in foods))
    if len(names) > MAX_OPTIONS:
        return Reply(f"Уточни: {', '.join(names[:MAX_OPTIONS])} или другое?")
    return Reply(f"Уточни: {', '.join(names[:-1])} или {names[-1]}?")


def _one_or_ask(found: list[Found]) -> Found | Reply | None:
    """Один продукт — он; несколько разных — переспросить; пусто — None."""
    distinct = list({f.food.name: f for f in found}.values())
    if not distinct:
        return None
    return distinct[0] if len(distinct) == 1 else _ask([f.food for f in distinct])


def _from_diary(root: Path, wanted: frozenset[str]) -> Found | None:
    same = [e for e in diary.load_all(root) if tokens(e.food.name) == wanted]
    if not same:
        return None
    return Found(max(same, key=lambda e: e.seq).food, "diary")


def _own(root: Path, match: Callable[[frozenset[str]], bool]) -> list[Found]:
    return [Found(f, "own") for f, _ in products.load(root) if match(tokens(f.name))]


def _table(match: Callable[[frozenset[str]], bool]) -> list[Found]:
    return [Found(t.food, "table") for t in table_foods() if any(match(tokens(k)) for k in t.keys)]


def by_name(root: Path, name: str) -> Found | Reply:
    """Продукт по названию: своя база, дневник, таблица; затем частичное совпадение.

    Частичное — сказанное название входит в название продукта («гречка» → «гречка варёная»).
    """
    wanted = tokens(name)
    if not wanted:
        return Reply(NOTHING)

    def exact(have: frozenset[str]) -> bool:
        return have == wanted

    def partial(have: frozenset[str]) -> bool:
        return wanted <= have

    found = (
        _one_or_ask(_own(root, exact))
        or _from_diary(root, wanted)
        or _one_or_ask(_table(exact))
        or _one_or_ask(_own(root, partial) + _table(partial))
    )
    return found or Reply(f"Не знаю калорийность «{name}». Скажи, сколько ккал на 100 г.")


def _off_reply(result: OffResult, code: str) -> str:
    if result.status == "offline":
        return "Нет связи с Open Food Facts — штрихкод не проверить. Скажи название продукта."
    if result.status == "no_kcal":
        return f"Нашла «{result.name}», но калорийности в базе нет. Скажи, сколько ккал на 100 г."
    return f"Не знаю продукт со штрихкодом {code}. Скажи название и сколько ккал на 100 г — запомню."


def _off_note(result: OffResult) -> str:
    if result.status == "offline":
        return "Нет связи с Open Food Facts — считаю по названию."
    return "По штрихкоду калорийность не нашла — считаю по названию."


async def resolve(root: Path, name: str, barcode: str, off: OpenFoodFacts) -> Found | Reply:
    """Калорийность продукта по штрихкоду и/или названию (порядок — в описании модуля).

    Штрихкод не помог, но есть название — ищется по названию с пояснением в `note`.
    """
    if not barcode.strip():
        return by_name(root, name)
    code = valid_barcode(barcode)
    if code is None:
        if not tokens(name):
            return Reply(bad_barcode(barcode))
        note = bad_barcode(barcode, "считаю по названию.")
    else:
        own = products.by_barcode(root, code)
        if own is not None:
            return Found(own, "own")
        result = await off.lookup(code)
        if result.food is not None:
            products.upsert(root, result.food, "off")
            return Found(result.food, "off")
        if not tokens(name):
            return Reply(_off_reply(result, code))
        note = _off_note(result)
    found = by_name(root, name)
    return replace(found, note=note) if isinstance(found, Found) else Reply(f"{note} {found.text}")
