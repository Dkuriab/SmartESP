"""Тесты записи съеденного: порядок поиска калорий, вес, штуки, ответы."""

import json
from pathlib import Path

from .conftest import BARCODE, Caller, Clock, FakeOff

DAY_FILE = Path("home") / "diary" / "2026-11.jsonl"


def _diary(data_dir: Path) -> list[dict[str, object]]:
    path = data_dir / DAY_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ocr_product() -> dict[str, object]:
    return {
        "product_name_ru": "Гречка ядрица",
        "brands": "Мистраль",
        "product_quantity": 900,
        "nutriments": {"energy-kcal_100g": 313, "proteins_100g": 12.6, "fat_100g": 3.3},
    }


async def test_table_exact_synonym(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "гречневая каша", "grams": 200})
    assert out == "Записала: гречка варёная, 200 г — 184 ккал. За сегодня 184 ккал."
    [entry] = _diary(data_dir)
    assert entry["name"] == "гречка варёная"
    assert entry["grams"] == 200
    assert entry["time"] == "2026-11-19T10:32"
    assert entry["source"] == "table"


async def test_spec_example_and_day_total(call: Caller) -> None:
    await call("food_log", {"what": "гречневая каша", "grams": 200})
    out = await call("food_log", {"what": "Гречку сухую", "grams": 150})
    assert out == "Записала: гречка (сухая), 150 г — 515 ккал. За сегодня 699 ккал."


async def test_ambiguous_asks_and_writes_nothing(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "гречку", "grams": 150})
    assert out == "Уточни: гречка (сухая) или гречка варёная?"
    assert _diary(data_dir) == []


async def test_unknown_asks_for_kcal(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "амброзия", "grams": 100})
    assert out == "Не знаю калорийность «амброзия». Скажи, сколько ккал на 100 г."
    assert _diary(data_dir) == []


async def test_nothing_to_log(call: Caller) -> None:
    assert await call("food_log", {}) == "Что записать? Скажи продукт и вес."


async def test_no_grams_asks(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "гречка варёная"})
    assert out == "Скажи вес в граммах: гречка варёная."
    assert _diary(data_dir) == []


async def test_bad_grams(call: Caller) -> None:
    assert await call("food_log", {"what": "яблоко", "grams": -5}) == "Вес должен быть больше нуля."
    out = await call("food_log", {"what": "яблоко", "grams": 6000})
    assert out == "Записать 6 кг (яблоко)? Это много — скажи вес порции."


async def test_grams_inside_what(call: Caller) -> None:
    out = await call("food_log", {"what": "гречка варёная 100 г"})
    assert out == "Записала: гречка варёная, 100 г — 92 ккал. За сегодня 92 ккал."


async def test_pieces_with_known_weight(call: Caller) -> None:
    out = await call("food_log", {"what": "2 яйца"})
    assert out == "Записала: яйцо куриное, 2 штуки, 110 г — 157 ккал. За сегодня 157 ккал."
    out = await call("food_log", {"what": "яйцо"})
    assert out == "Записала: яйцо куриное, 1 штука, 55 г — 79 ккал. За сегодня 236 ккал."


async def test_grams_win_over_pieces(call: Caller) -> None:
    out = await call("food_log", {"what": "2 яйца", "grams": 100})
    assert out == "Записала: яйцо куриное, 100 г — 143 ккал. За сегодня 143 ккал."


async def test_pieces_without_weight_ask_grams(call: Caller) -> None:
    assert await call("food_log", {"what": "2 творога"}) == "Скажи вес в граммах: творог 5%."


async def test_own_product_beats_table(call: Caller, data_dir: Path) -> None:
    out = await call("product_add", {"name": "Гречка варёная", "kcal_100g": 100})
    assert out == "Запомнила: Гречка варёная — 100 ккал на 100 г."
    out = await call("food_log", {"what": "гречка варёная", "grams": 50})
    assert out == "Записала: Гречка варёная, 50 г — 50 ккал. За сегодня 50 ккал."
    assert _diary(data_dir)[0]["source"] == "own"


async def test_product_pack_weight_and_count(call: Caller) -> None:
    out = await call("product_add", {"name": "йогурт Чудо", "kcal_100g": 90, "pack_grams": 125})
    assert out == "Запомнила: йогурт Чудо — 90 ккал на 100 г, упаковка 125 г."
    out = await call("food_log", {"what": "йогурт чудо"})
    assert out == "Записала: йогурт Чудо, 1 упаковка, 125 г — 113 ккал. За сегодня 113 ккал."
    out = await call("food_log", {"what": "2 йогурта чудо"})
    assert out == "Записала: йогурт Чудо, 2 упаковки, 250 г — 225 ккал. За сегодня 338 ккал."


async def test_product_add_updates_and_validates(call: Caller, data_dir: Path) -> None:
    await call("product_add", {"name": "сырники мамины", "kcal_100g": 220})
    out = await call("product_add", {"name": "Сырники  мамины", "kcal_100g": 230, "protein": 15})
    assert out == "Обновила: Сырники мамины — 230 ккал на 100 г."
    products = json.loads((data_dir / "home" / "products.json").read_text(encoding="utf-8"))
    assert [p["name"] for p in products] == ["Сырники мамины"]
    assert products[0]["protein"] == 15
    assert await call("product_add", {"name": " ", "kcal_100g": 100}) == "Скажи название продукта."
    bad_kcal = "Калорийность на 100 г должна быть от 0 до 900."
    assert await call("product_add", {"name": "x", "kcal_100g": 1000}) == bad_kcal
    out = await call("product_add", {"name": "x", "kcal_100g": 100, "fat": 120})
    assert out == "Белки, жиры и углеводы — от 0 до 100 г на 100 г."
    out = await call("product_add", {"name": "x", "kcal_100g": 100, "barcode": "123"})
    assert out == "Штрихкод «123» не похож на настоящий — проверь цифры."


async def test_own_barcode(call: Caller, off: FakeOff) -> None:
    await call("product_add", {"name": "хлебцы Мои", "kcal_100g": 380, "barcode": BARCODE})
    out = await call("food_log", {"barcode": BARCODE, "grams": 20})
    assert out == "Записала: хлебцы Мои, 20 г — 76 ккал. За сегодня 76 ккал."
    assert off.requests == []


async def test_open_food_facts_found_and_cached(call: Caller, off: FakeOff, data_dir: Path) -> None:
    off.products[BARCODE] = _ocr_product()
    out = await call("food_log", {"barcode": BARCODE, "grams": 100})
    assert out == "Записала: Гречка ядрица Мистраль, 100 г — 313 ккал. За сегодня 313 ккал."
    out = await call("food_log", {"barcode": BARCODE})
    assert out == ("Записала: Гречка ядрица Мистраль, 1 упаковка, 900 г — 2817 ккал. За сегодня 3130 ккал.")
    assert len(off.requests) == 1
    products = json.loads((data_dir / "home" / "products.json").read_text(encoding="utf-8"))
    assert products[0]["barcode"] == BARCODE
    assert products[0]["source"] == "off"


async def test_open_food_facts_missing(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"barcode": BARCODE, "grams": 100})
    assert out == (
        f"Не знаю продукт со штрихкодом {BARCODE}. Скажи название и сколько ккал на 100 г — запомню."
    )
    assert _diary(data_dir) == []


async def test_open_food_facts_no_kcal(call: Caller, off: FakeOff) -> None:
    off.products[BARCODE] = {"product_name": "Вода", "nutriments": {}}
    out = await call("food_log", {"barcode": BARCODE, "grams": 100})
    assert out == "Нашла «Вода», но калорийности в базе нет. Скажи, сколько ккал на 100 г."


async def test_offline_without_name(call: Caller, off: FakeOff) -> None:
    off.offline = True
    out = await call("food_log", {"barcode": BARCODE, "grams": 100})
    assert out == "Нет связи с Open Food Facts — штрихкод не проверить. Скажи название продукта."


async def test_offline_falls_back_to_name(call: Caller, off: FakeOff) -> None:
    off.offline = True
    out = await call("food_log", {"barcode": BARCODE, "what": "гречка варёная", "grams": 100})
    assert out == (
        "Нет связи с Open Food Facts — считаю по названию. "
        "Записала: гречка варёная, 100 г — 92 ккал. За сегодня 92 ккал."
    )


async def test_bad_barcode(call: Caller, off: FakeOff) -> None:
    out = await call("food_log", {"barcode": "123", "grams": 100})
    assert out == "Штрихкод «123» не похож на настоящий — проверь цифры."
    out = await call("food_log", {"barcode": "123", "what": "яблоко", "grams": 100})
    assert out.startswith("Штрихкод «123» не похож на настоящий — считаю по названию. Записала: яблоко")
    assert off.requests == []


async def test_diary_remembers_choice_like_yesterday(call: Caller, clock: Clock, data_dir: Path) -> None:
    assert (await call("food_log", {"what": "гречку", "grams": 150})).startswith("Уточни")
    await call("food_log", {"what": "гречка (сухая)", "grams": 150})
    assert _diary(data_dir)[-1]["said"] == "гречку"
    clock.now = clock.now.replace(day=20)
    out = await call("food_log", {"what": "гречка", "grams": 100})
    assert out == "Записала: гречка (сухая), 100 г — 343 ккал. За сегодня 343 ккал."
    assert _diary(data_dir)[-1]["source"] == "diary"


async def test_choice_is_remembered_only_right_after_question(call: Caller, clock: Clock) -> None:
    await call("food_log", {"what": "гречку", "grams": 150})
    await call("food_log", {"what": "яблоко", "grams": 100})
    await call("food_log", {"what": "гречка (сухая)", "grams": 150})
    clock.now = clock.now.replace(day=20)
    assert (await call("food_log", {"what": "гречка", "grams": 100})).startswith("Уточни")


async def test_diary_matches_said_words(call: Caller, clock: Clock, data_dir: Path) -> None:
    await call("product_add", {"name": "Суп от бабушки Нины", "kcal_100g": 60})
    await call("food_log", {"what": "Суп от бабушки Нины", "grams": 300})
    clock.now = clock.now.replace(day=20)
    out = await call("food_log", {"what": "суп бабушки", "grams": 100})
    assert out.startswith("Уточни")
    await call("food_log", {"what": "Суп от бабушки Нины", "grams": 100})
    clock.now = clock.now.replace(day=21)
    out = await call("food_log", {"what": "суп бабушки", "grams": 200})
    assert out == "Записала: Суп от бабушки Нины, 200 г — 120 ккал. За сегодня 120 ккал."
    assert _diary(data_dir)[-1]["source"] == "diary"


async def test_when_yesterday_and_bad_when(call: Caller, data_dir: Path) -> None:
    out = await call("food_log", {"what": "яблоко", "grams": 100, "when": "вчера"})
    assert out == "Записала: яблоко, 100 г — 52 ккал. За 18 ноября 52 ккал."
    assert _diary(data_dir)[0]["time"] == "2026-11-18T10:32"
    out = await call("food_log", {"what": "яблоко", "grams": 100, "when": "завтра"})
    assert out == "Не поняла время «завтра». Скажи, например, «вчера» или «8:30»."


async def test_people_are_separate(call: Caller, data_dir: Path) -> None:
    await call("food_log", {"what": "яблоко", "grams": 100}, person="Аня")
    assert (data_dir / "аня" / "diary" / "2026-11.jsonl").exists()
    assert await call("food_today") == "Сегодня записей нет."
    out = await call("food_today", person="Аня")
    assert out.startswith("Сегодня 52 ккал")


async def test_person_name_cannot_escape(call: Caller, data_dir: Path) -> None:
    await call("food_log", {"what": "яблоко", "grams": 100}, person="../x")
    assert not (data_dir.parent / "x").exists()
    assert (data_dir / "x" / "diary" / "2026-11.jsonl").exists()


async def test_undo(call: Caller, data_dir: Path) -> None:
    assert await call("food_undo") == "Дневник пуст — убирать нечего."
    await call("food_log", {"what": "яблоко", "grams": 100})
    await call("food_log", {"what": "гречка варёная", "grams": 200, "when": "вчера"})
    assert await call("food_undo") == "Убрала: гречка варёная, 200 г — 184 ккал."
    assert [e["name"] for e in _diary(data_dir)] == ["яблоко"]
    assert await call("food_undo") == "Убрала: яблоко, 100 г — 52 ккал."
    assert await call("food_undo") == "Дневник пуст — убирать нечего."


UPC_A = "036000291452"
UPC_AS_EAN13 = "0" + UPC_A  # так UPC-A отдаёт zxing-cpp в Telegram-боте


async def test_upc_a_and_its_ean13_form_are_one_product(call: Caller, off: FakeOff) -> None:
    await call("product_add", {"name": "батончик", "kcal_100g": 400, "barcode": UPC_A})
    out = await call("food_log", {"barcode": UPC_AS_EAN13, "grams": 50})
    assert out == "Записала: батончик, 50 г — 200 ккал. За сегодня 200 ккал."
    assert off.requests == []


async def test_upc_a_cache_hit_from_ean13_form(call: Caller, off: FakeOff) -> None:
    off.products[UPC_AS_EAN13] = {"product_name": "Bar", "nutriments": {"energy-kcal_100g": 500}}
    await call("food_log", {"barcode": UPC_AS_EAN13, "grams": 10})
    out = await call("food_log", {"barcode": UPC_A, "grams": 10})
    assert out == "Записала: Bar, 10 г — 50 ккал. За сегодня 100 ккал."
    assert len(off.requests) == 1
