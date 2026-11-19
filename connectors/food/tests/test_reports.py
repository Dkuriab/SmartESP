"""Тесты итогов: сегодня, за несколько дней, поиск в дневнике."""

from .conftest import Caller, Clock


async def _log_two(call: Caller) -> None:
    await call("food_log", {"what": "гречка (сухая)", "grams": 150})
    await call("food_log", {"what": "гречка варёная", "grams": 200})


async def test_today_empty(call: Caller) -> None:
    assert await call("food_today") == "Сегодня записей нет."


async def test_today_totals(call: Caller) -> None:
    await _log_two(call)
    await call("food_log", {"what": "яблоко", "grams": 100, "when": "вчера"})
    assert await call("food_today") == (
        "Сегодня 699 ккал: гречка (сухая), гречка варёная. Белки 26,8 г, жиры 6,3 г, углеводы 147,1 г."
    )


async def test_today_many_items_shortened(call: Caller) -> None:
    for what in ["яблоко", "банан", "груша", "киви", "апельсин", "мандарин", "яблоко"]:
        await call("food_log", {"what": what, "grams": 100})
    out = await call("food_today")
    assert "яблоко, банан, груша, киви, апельсин и ещё 1." in out


async def test_summary(call: Caller, clock: Clock) -> None:
    await _log_two(call)
    await call("food_log", {"what": "яблоко", "grams": 100, "when": "позавчера"})
    await call("food_log", {"what": "яблоко", "grams": 100, "when": "2026-11-01"})
    assert await call("food_summary", {"days": 3}) == (
        "За 3 дня 751 ккал, в среднем 375 ккал в день с записями. "
        "В среднем белки 13,5 г, жиры 3,3 г, углеводы 80,4 г. "
        "По дням: 17 ноября — 52, 19 ноября — 699."
    )


async def test_summary_default_week_and_empty(call: Caller) -> None:
    assert await call("food_summary") == "За 7 дней записей нет."
    assert await call("food_summary", {"days": 1}) == "За 1 день записей нет."
    assert await call("food_summary", {"days": 0}) == "За 1 день записей нет."
    await call("food_log", {"what": "яблоко", "grams": 100})
    assert (await call("food_summary")).startswith("За 7 дней 52 ккал")


async def test_find(call: Caller) -> None:
    await call("food_log", {"what": "гречка (сухая)", "grams": 150, "when": "вчера 9:05"})
    await call("food_log", {"what": "яблоко", "grams": 100})
    await call("food_log", {"what": "гречка варёная", "grams": 200})
    assert await call("food_find", {"query": "гречку"}) == (
        "Нашла: 19 ноября в 10:32 — гречка варёная, 200 г, 184 ккал; "
        "18 ноября в 9:05 — гречка (сухая), 150 г, 515 ккал."
    )
    assert await call("food_find", {"query": "торт"}) == "Не нашла «торт» в дневнике."
    assert await call("food_find", {"query": " "}) == "Что найти? Скажи название."
