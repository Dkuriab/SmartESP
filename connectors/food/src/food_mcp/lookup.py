"""Поиск калорийности: штрихкод — своя база → (Open Food Facts, если включён) →
barcode-list.ru (только название) → таблица; по названию — своя база → дневник → таблица.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from . import barcode_list, barcode_match, diary, products
from .barcode_list import BarcodeList, NameResult
from .food import Food
from .names import tokens
from .off import OffResult, OpenFoodFacts, valid_barcode
from .speech import kcal as kcal_text
from .speech import num
from .table import table_foods

MAX_OPTIONS = 3
NOTHING = "Что записать? Скажи продукт и вес."


@dataclass(frozen=True)
class Found:
    """Продукт нашёлся; `source` — откуда («own», «off», «diary», «table»), `note` — пояснение."""

    food: Food
    source: str
    note: str = ""


@dataclass(frozen=True)
class Reply:
    """Не нашлось или неоднозначно: ответ человеку, запись не делается.

    `options` — названия, которые предложены на выбор (пусто — не вопрос «какой из»).
    """

    text: str
    options: tuple[str, ...] = ()


def bad_barcode(raw: str, tail: str = "проверь цифры.") -> str:
    return f"Штрихкод «{raw.strip()}» не похож на настоящий — {tail}"


def _ask(found: list[Found]) -> Reply:
    """Вопрос «какой из»: один вариант — «это X?», до трёх — списком, больше — «или другое»."""
    names = tuple(dict.fromkeys(f.food.name for f in found))
    if len(names) == 1:
        return Reply(f"Уточни: это {names[0]}?", names)
    if len(names) > MAX_OPTIONS:
        return Reply(f"Уточни: {', '.join(names[:MAX_OPTIONS])} или другое?", names[:MAX_OPTIONS])
    return Reply(f"Уточни: {', '.join(names[:-1])} или {names[-1]}?", names)


def _one_or_ask(found: list[Found]) -> Found | Reply | None:
    """Один продукт — он; несколько разных — переспросить; пусто — None."""
    distinct = list({f.food.name: f for f in found}.values())
    if not distinct:
        return None
    return distinct[0] if len(distinct) == 1 else _ask(distinct)


def _offer(found: list[Found]) -> Reply | None:
    """Частичное совпадение никогда не пишется молча — только предлагается."""
    return _ask(found) if found else None


def _from_diary(root: Path, wanted: frozenset[str]) -> Found | None:
    """«Как в прошлый раз»: запись, где так же было сказано или так же назван продукт."""
    same = [e for e in diary.load_all(root) if wanted in (tokens(e.said), tokens(e.food.name))]
    if not same:
        return None
    return Found(max(same, key=lambda e: e.seq).food, "diary")


def _own(root: Path, match: Callable[[frozenset[str]], bool]) -> list[Found]:
    return [Found(f, "own") for f, _ in products.load(root) if match(tokens(f.name))]


def _table(match: Callable[[frozenset[str]], bool]) -> list[Found]:
    return [Found(t.food, "table") for t in table_foods() if any(match(tokens(k)) for k in t.keys)]


def by_name(root: Path, name: str) -> Found | Reply:
    """Продукт по названию: своя база, дневник, таблица — только точное совпадение.

    Сказанное лишь входит в название продукта («мясо» → «плов с мясом») — продукт
    предлагается вопросом, а не записывается.
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
        or _offer(_own(root, partial) + _table(partial))
    )
    return found or Reply(f"Не знаю калорийность «{name}». Скажи, сколько ккал на 100 г.")


@dataclass(frozen=True)
class Lookups:
    """Сетевые справочники: `off` — Open Food Facts (None — выключен), `names` — barcode-list.ru."""

    names: BarcodeList
    off: OpenFoodFacts | None = None


def _off_reply(result: OffResult | None) -> str | None:
    """Ответ про Open Food Facts, если он что-то сказал сверх «не нашлось»."""
    if result is None:
        return None
    if result.status == "offline":
        return "Нет связи с Open Food Facts — штрихкод не проверить. Скажи название продукта."
    if result.status == "no_kcal":
        return f"Нашла «{result.name}», но калорийности в базе нет. Скажи, сколько ккал на 100 г."
    return None


def _names_reply(result: NameResult, code: str) -> str:
    if result.status == "offline":
        return "Нет связи со справочником штрихкодов — штрихкод не проверить. Скажи название продукта."
    if result.status == "busy":
        return (
            "Справочник штрихкодов отвечает не чаще раза в 10 секунд. Повтори чуть позже или скажи название."
        )
    return f"Не знаю продукт со штрихкодом {code}. Скажи название и сколько ккал на 100 г — запомню."


def _names_note(result: NameResult, off: OffResult | None) -> str:
    if off is not None and off.status == "offline":
        return "Нет связи с Open Food Facts — считаю по названию."
    if result.status == "offline":
        return "Нет связи со справочником штрихкодов — считаю по названию."
    if result.status == "found":
        return f"По штрихкоду нашла «{result.name}»."
    return "По штрихкоду калорийность не нашла — считаю по названию."


def _from_barcode_name(root: Path, code: str, name: str) -> Reply:
    """Название с barcode-list.ru: предложить похожее (не писать молча) или спросить ккал."""
    pack = barcode_match.pack_grams(name)
    pack_text = f", упаковка {num(pack)} г" if pack else ""
    found = barcode_match.candidates(root, name)
    if not found:
        return Reply(
            f"Нашла: {name}{pack_text}. Калорийности не знаю — скажи, сколько ккал на 100 г, "
            f"и я запомню по штрихкоду {code}."
        )
    options = tuple(c.food.name for c in found)
    text = ", ".join(f"«{c.food.name}» — {kcal_text(c.food.kcal_100g)} ккал на 100 г" for c in found)
    return Reply(
        f"Нашла: {name}{pack_text}. Похоже на {text}. Записать? "
        "Если да — повтори запись с этим названием и тем же штрихкодом.",
        options,
    )


def _with_pack(found: Found, pack: float) -> Found:
    """Продукту без веса штуки и упаковки подставляется упаковка из названия товара."""
    food = found.food
    if pack and not food.piece_grams and not food.pack_grams:
        return replace(found, food=replace(food, pack_grams=pack))
    return found


async def _network_names(
    root: Path, code: str, lookups: Lookups, now: datetime
) -> tuple[Found | None, OffResult | None, NameResult]:
    """Open Food Facts (если включён), затем название с barcode-list.ru (кэш — 30 дней)."""
    off_result: OffResult | None = None
    if lookups.off is not None:
        off_result = await lookups.off.lookup(code)
        if off_result.food is not None:
            products.upsert(root, off_result.food, "off")
            return Found(off_result.food, "off"), off_result, NameResult("missing")
    cached = barcode_list.cached(root, code, now)
    names = cached or await lookups.names.lookup(code)
    if cached is None:
        barcode_list.remember(root, code, names, now)
    return None, off_result, names


async def resolve(root: Path, name: str, barcode: str, lookups: Lookups, now: datetime) -> Found | Reply:
    """Калорийность продукта по штрихкоду и/или названию (порядок — в описании модуля).

    Штрихкод не помог, но есть название — ищется по названию с пояснением в `note`.
    Название с barcode-list.ru само калорийность не даёт: продукт таблицы предлагается
    вопросом (запись — только после подтверждения, названием продукта).
    """
    if not barcode.strip():
        return by_name(root, name)
    code = valid_barcode(barcode)
    off_result: OffResult | None = None
    names = NameResult("missing")
    if code is None:
        if not tokens(name):
            return Reply(bad_barcode(barcode))
        note = bad_barcode(barcode, "считаю по названию.")
    else:
        own = products.by_barcode(root, code)
        if own is not None:
            return Found(own, "own")
        online, off_result, names = await _network_names(root, code, lookups, now)
        if online is not None:
            return online
        if not tokens(name):
            if names.status == "found":
                return _from_barcode_name(root, code, names.name)
            return Reply(_off_reply(off_result) or _names_reply(names, code))
        note = _names_note(names, off_result)
    found = by_name(root, name)
    if isinstance(found, Found):
        pack = barcode_match.pack_grams(names.name) if names.status == "found" else 0.0
        return replace(_with_pack(found, pack), note=note)
    return replace(found, text=f"{note} {found.text}")
