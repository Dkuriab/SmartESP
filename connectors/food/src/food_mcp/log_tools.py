"""Инструменты записи: съел, свой продукт, убрать последнее."""

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from . import diary, products
from .context import root_of
from .diary import Entry
from .food import Food
from .lookup import NOTHING, Found, bad_barcode, resolve
from .names import parse_amount, tokens
from .off import OpenFoodFacts, valid_barcode
from .speech import day_words, kcal, num, plural
from .when import parse_when

MAX_GRAMS = 5000
MAX_KCAL_100G = 900


def portion(food: Food, grams: float, count: int) -> tuple[float, int] | None:
    """Вес порции и штук: граммы сказаны — они; иначе штуки × вес штуки/упаковки; иначе None."""
    if grams > 0:
        return grams, 0
    if food.unit_grams > 0:
        pieces = count or 1
        return pieces * food.unit_grams, pieces
    return None


def describe(entry: Entry) -> str:
    """«гречка, 150 г — 515 ккал» или «яйцо, 2 штуки, 110 г — 157 ккал»."""
    amount = f"{num(entry.grams)} г"
    if entry.count:
        n = entry.count
        if entry.food.piece_grams:
            unit = plural(n, "штука", "штуки", "штук")
        else:
            unit = plural(n, "упаковка", "упаковки", "упаковок")
        amount = f"{n} {unit}, {amount}"
    return f"{entry.food.name}, {amount} — {kcal(entry.kcal)} ккал"


def day_label(day: date, today: date) -> str:
    """«За сегодня» или «За 18 ноября»."""
    return "За сегодня" if day == today else f"За {day_words(day)}"


def _grams_error(grams: float) -> str | None:
    if grams < 0:
        return "Вес должен быть больше нуля."
    if grams > MAX_GRAMS:
        return f"Слишком большой вес: {num(grams)} г. Проверь."
    return None


def _product_error(name: str, kcal_100g: float, macros: tuple[float, ...], barcode: str) -> str | None:
    if not name:
        return "Скажи название продукта."
    if not 0 <= kcal_100g <= MAX_KCAL_100G:
        return f"Калорийность на 100 г должна быть от 0 до {MAX_KCAL_100G}."
    if not all(0 <= v <= 100 for v in macros):
        return "Белки, жиры и углеводы — от 0 до 100 г на 100 г."
    if barcode.strip() and valid_barcode(barcode) is None:
        return bad_barcode(barcode)
    return None


async def log_food(
    root: Path, off: OpenFoodFacts, now: datetime, what: str, grams: float, barcode: str, when: str
) -> str:
    """Записывает съеденное и возвращает ответ для озвучки."""
    amount = parse_amount(what)
    grams = grams or amount.grams
    error = _grams_error(grams)
    if error:
        return error
    eaten = parse_when(when, now)
    if eaten is None:
        return f"Не поняла время «{when.strip()}». Скажи, например, «вчера» или «8:30»."
    if not tokens(amount.name) and not barcode.strip():
        return NOTHING
    found = await resolve(root, amount.name, barcode, off)
    if not isinstance(found, Found):
        return found.text
    weight = portion(found.food, grams, amount.count)
    if weight is None:
        return f"Скажи вес в граммах: {found.food.name}."
    entry = diary.add(root, eaten, found.food, weight[0], weight[1], found.source)
    total = sum(e.kcal for e in diary.on_day(root, entry.time.date()))
    label = day_label(entry.time.date(), now.date())
    text = f"Записала: {describe(entry)}. {label} {kcal(total)} ккал."
    return f"{found.note} {text}" if found.note else text


def add_product(
    root: Path, name: str, kcal_100g: float, macros: tuple[float, float, float], barcode: str, pack: float
) -> str:
    """Добавляет или обновляет свой продукт; возвращает ответ для озвучки."""
    clean = " ".join(name.split())
    error = _product_error(clean, kcal_100g, macros, barcode)
    if error:
        return error
    if not 0 <= pack <= MAX_GRAMS:
        return f"Вес упаковки — от 0 до {MAX_GRAMS} г."
    code = valid_barcode(barcode) or ""
    food = Food(clean, kcal_100g, *macros, barcode=code, pack_grams=pack)
    verb = "Обновила" if products.upsert(root, food, "own") else "Запомнила"
    pack_text = f", упаковка {num(pack)} г" if pack else ""
    return f"{verb}: {clean} — {kcal(kcal_100g)} ккал на 100 г{pack_text}."


def register(server: MCPServer, data_dir: Path, now: Callable[[], datetime], off: OpenFoodFacts) -> None:
    """Регистрирует инструменты записи на сервере."""

    @server.tool(
        description=(
            "Записать съеденное в дневник питания и посчитать калории. "
            "Пример: what «гречка», grams 150; what «2 яйца»; штрихкод — в barcode."
        )
    )
    async def food_log(
        ctx: Context,
        what: Annotated[str, Field(description="Что съел: «гречка», «2 яйца»")] = "",
        grams: Annotated[float, Field(description="Вес в граммах; 0 — не сказан")] = 0,
        barcode: Annotated[str, Field(description="Штрихкод с упаковки, если есть")] = "",
        when: Annotated[str, Field(description="Когда: «вчера», «8:30»; пусто — сейчас")] = "",
    ) -> str:
        return await log_food(root_of(ctx, data_dir), off, now(), what, grams, barcode, when)

    @server.tool(
        description=(
            "Запомнить продукт: ккал и белки/жиры/углеводы на 100 г. "
            "Для своих блюд и продуктов, которых нет по штрихкоду. Пример: «сырники мамины», 220."
        )
    )
    def product_add(
        ctx: Context,
        name: str,
        kcal_100g: float,
        protein: float = 0,
        fat: float = 0,
        carbs: float = 0,
        barcode: str = "",
        pack_grams: Annotated[float, Field(description="Вес упаковки в граммах; 0 — нет")] = 0,
    ) -> str:
        root = root_of(ctx, data_dir)
        return add_product(root, name, kcal_100g, (protein, fat, carbs), barcode, pack_grams)

    @server.tool(description="Убрать последнюю запись из дневника питания.")
    def food_undo(ctx: Context) -> str:
        entry = diary.pop_last(root_of(ctx, data_dir))
        if entry is None:
            return "Дневник пуст — убирать нечего."
        return f"Убрала: {describe(entry)}."
