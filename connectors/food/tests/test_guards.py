"""Тесты защит: частичное совпадение не пишется молча, большой вес, время в будущем."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from .conftest import BARCODE, Caller, Clock, FakeOff


def _names(data_dir: Path) -> list[str]:
    path = data_dir / "home" / "diary" / "2026-11.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["name"] for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("what", ["мясо", "рыба", "фрукты", "суп", "молочный"])
async def test_partial_match_asks_instead_of_logging(call: Caller, data_dir: Path, what: str) -> None:
    out = await call("food_log", {"what": what, "grams": 100})
    assert out.startswith(("Уточни", "Не знаю калорийность")), out
    assert _names(data_dir) == []


async def test_single_partial_match_is_offered(call: Caller, data_dir: Path) -> None:
    assert await call("food_log", {"what": "фрукты", "grams": 100}) == "Уточни: это йогурт фруктовый?"
    assert _names(data_dir) == []


async def test_partial_options_capped_at_three(call: Caller) -> None:
    out = await call("food_log", {"what": "картошка", "grams": 100})
    assert out.startswith("Уточни: ") and out.endswith(" или другое?")
    assert out.count(",") == 2


@pytest.mark.parametrize(
    ("what", "name"),
    [("вода", "вода"), ("чай с сахаром", "чай с сахаром"), ("чай", "чай")],
)
async def test_exact_names_still_log(call: Caller, data_dir: Path, what: str, name: str) -> None:
    assert (await call("food_log", {"what": what, "grams": 200})).startswith(f"Записала: {name}, 200 г")
    assert _names(data_dir) == [name]


async def test_water_is_zero(call: Caller) -> None:
    out = await call("food_log", {"what": "вода", "grams": 250})
    assert out == "Записала: вода, 250 г — 0 ккал. За сегодня 0 ккал."


async def test_too_many_pieces_asks(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "100 хлеба"})
    assert out == "Записать 100 штук, 3 кг (хлеб белый)? Это много — скажи вес порции."
    out = await call("food_log", {"what": "21 яйцо"})
    assert out.startswith("Записать 21 штуку")
    assert _names(data_dir) == []
    assert (await call("food_log", {"what": "20 яиц"})).startswith("Записала: яйцо куриное, 20 штук")


async def test_too_heavy_portion_asks(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "яблоко", "grams": 2001})
    assert out == "Записать 2 кг (яблоко)? Это много — скажи вес порции."
    assert (await call("food_log", {"what": "яблоко", "grams": 2000})).startswith("Записала:")


async def test_big_pack_is_not_default(call: Caller, off: FakeOff, data_dir: Path) -> None:
    off.products[BARCODE] = {
        "product_name": "Рис мешок",
        "product_quantity": 6000,
        "nutriments": {"energy-kcal_100g": 350},
    }
    assert await call("food_log", {"barcode": BARCODE}) == "Скажи вес в граммах: Рис мешок."
    assert _names(data_dir) == []
    await call("product_add", {"name": "сыр кусок", "kcal_100g": 350, "pack_grams": 1000})
    assert (await call("food_log", {"what": "сыр кусок"})).startswith("Записала: сыр кусок, 1 упаковка")


async def test_late_clock_time_after_midnight_is_yesterday(
    call: Caller, clock: Clock, data_dir: Path
) -> None:
    clock.now = datetime(2026, 11, 19, 0, 30)
    out = await call("food_log", {"what": "яблоко", "grams": 100, "when": "23:30"})
    assert out == "Записала: яблоко, 100 г — 52 ккал. За 18 ноября 52 ккал."
    assert await call("food_today") == "Сегодня записей нет."


async def test_unreadable_diary_lines_survive_add_and_undo(call: Caller, data_dir: Path) -> None:
    path = data_dir / "home" / "diary" / "2026-11.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("правка руками\n", encoding="utf-8")
    await call("food_log", {"what": "яблоко", "grams": 100})
    assert await call("food_undo") == "Убрала: яблоко, 100 г — 52 ккал."
    assert path.read_text(encoding="utf-8") == "правка руками\n"
