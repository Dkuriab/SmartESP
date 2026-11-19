"""Инструменты итогов: сегодня, за несколько дней, поиск в дневнике."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer

from . import diary
from .context import root_of
from .diary import Entry
from .names import tokens
from .speech import day_words, kcal, num, plural

MAX_ITEMS = 5
MAX_FOUND = 5
MAX_DAYS = 366


def _macros(entries: Sequence[Entry], days: int = 1) -> str:
    protein = sum(e.protein for e in entries) / days
    fat = sum(e.fat for e in entries) / days
    carbs = sum(e.carbs for e in entries) / days
    return f"белки {num(protein)} г, жиры {num(fat)} г, углеводы {num(carbs)} г"


def today_text(entries: Sequence[Entry]) -> str:
    """Итог дня: ккал, что ели (до пяти названий), Б/Ж/У."""
    if not entries:
        return "Сегодня записей нет."
    names = list(dict.fromkeys(e.food.name for e in entries))
    listed = ", ".join(names[:MAX_ITEMS])
    if len(names) > MAX_ITEMS:
        listed += f" и ещё {len(names) - MAX_ITEMS}"
    total = sum(e.kcal for e in entries)
    return f"Сегодня {kcal(total)} ккал: {listed}. {_macros(entries).capitalize()}."


def summary_text(entries: Sequence[Entry], days: int) -> str:
    """Итог за дни: всего, в среднем за день с записями, Б/Ж/У в среднем, по дням."""
    period = f"За {days} {plural(days, 'день', 'дня', 'дней')}"
    if not entries:
        return f"{period} записей нет."
    by_day: dict[str, float] = {}
    for entry in entries:
        key = day_words(entry.time.date())
        by_day[key] = by_day.get(key, 0) + entry.kcal
    total = sum(by_day.values())
    average = total / len(by_day)
    per_day = ", ".join(f"{day} — {kcal(value)}" for day, value in by_day.items())
    return (
        f"{period} {kcal(total)} ккал, в среднем {kcal(average)} ккал в день с записями. "
        f"В среднем {_macros(entries, len(by_day))}. По дням: {per_day}."
    )


def find_text(entries: Sequence[Entry], query: str) -> str:
    """Последние записи (до пяти), в названии которых есть сказанное."""
    wanted = tokens(query)
    if not wanted:
        return "Что найти? Скажи название."
    hits = [e for e in entries if wanted <= tokens(e.food.name)]
    if not hits:
        return f"Не нашла «{query.strip()}» в дневнике."
    latest = sorted(hits, key=lambda e: (e.time, e.seq), reverse=True)[:MAX_FOUND]
    return "Нашла: " + "; ".join(_found_line(e) for e in latest) + "."


def _found_line(entry: Entry) -> str:
    when = f"{day_words(entry.time.date())} в {entry.time.hour}:{entry.time:%M}"
    return f"{when} — {entry.food.name}, {num(entry.grams)} г, {kcal(entry.kcal)} ккал"


def register(server: MCPServer, data_dir: Path, now: Callable[[], datetime]) -> None:
    """Регистрирует инструменты итогов на сервере."""

    @server.tool(description="Сколько съедено сегодня: калории, белки, жиры, углеводы.")
    def food_today(ctx: Context) -> str:
        return today_text(diary.on_day(root_of(ctx, data_dir), now().date()))

    @server.tool(
        description="Итоги питания за несколько дней (по умолчанию 7): калории всего, в среднем и по дням."
    )
    def food_summary(ctx: Context, days: int = 7) -> str:
        days = min(max(days, 1), MAX_DAYS)
        today = now().date()
        start = today - timedelta(days=days - 1)
        entries = diary.load_all(root_of(ctx, data_dir))
        return summary_text([e for e in entries if start <= e.time.date() <= today], days)

    @server.tool(description="Найти в дневнике питания, когда и сколько ел. Пример: «гречка».")
    def food_find(ctx: Context, query: str) -> str:
        return find_text(diary.load_all(root_of(ctx, data_dir)), query)
