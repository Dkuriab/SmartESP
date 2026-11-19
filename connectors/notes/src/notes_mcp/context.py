"""Данные человека из вызова инструмента."""

from pathlib import Path

from mcp.server.mcpserver import Context

from .storage import person_root


def person_of(ctx: Context) -> str | None:
    """Человек из `_meta.person` вызова: строка или нет."""
    meta = ctx.request_context.meta
    value = meta.get("person") if meta else None
    return value if isinstance(value, str) and value.strip() else None


def root_of(ctx: Context, data_dir: Path) -> Path:
    """Папка данных человека (нет человека — общая «home»)."""
    return person_root(data_dir, person_of(ctx))
