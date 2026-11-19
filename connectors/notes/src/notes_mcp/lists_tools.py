"""Инструменты списков."""

from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer

from . import lists
from .context import root_of

# Псевдоним: параметр инструмента называется `list`, и он закрывает встроенный тип.
Items = list[str]


def _removal_reply(title: str, current: Items, removed: set[int], missing: Items, unclear: Items) -> str:
    parts: Items = []
    if removed:
        parts.append(f"Вычеркнула из «{title}»: {', '.join(current[i] for i in sorted(removed))}.")
    if missing:
        parts.append(f"Не нашла: {', '.join(missing)}.")
    parts.extend(f"Не вычеркнула, уточните: {text}." for text in unclear)
    return " ".join(parts) or "Нечего вычёркивать."


def register(server: MCPServer, data_dir: Path) -> None:
    """Регистрирует инструменты списков на сервере."""
    _register_edit(server, data_dir)
    _register_read(server, data_dir)


def _register_edit(server: MCPServer, data_dir: Path) -> None:
    """Инструменты, меняющие списки: добавить, вычеркнуть, очистить."""

    @server.tool(
        description="Добавить пункты в список (создастся сам). Пример: список «покупки», «молоко», «хлеб»."
    )
    def list_add(list: str, items: Items, ctx: Context) -> str:
        title, clean, root = lists.list_title(list), lists.clean_items(items), root_of(ctx, data_dir)
        if not title:
            return lists.NO_NAME
        if not clean:
            return "Нечего добавлять."
        lists.save(root, title, lists.load(root, title) + clean)
        return f"Добавила в «{title}»: {', '.join(clean)}."

    @server.tool(
        description="Вычеркнуть пункты из списка. Достаточно части: «молоко» вычеркнет «молоко 2 л»."
    )
    def list_remove(list: str, items: Items, ctx: Context) -> str:
        title, root = lists.list_title(list), root_of(ctx, data_dir)
        current = lists.load(root, title) if title else []
        removed, missing, unclear = lists.remove_items(current, items)
        if removed:
            lists.save(root, title, [item for i, item in enumerate(current) if i not in removed])
        return _removal_reply(title, current, removed, missing, unclear)

    @server.tool(description="Очистить список целиком. Пример: список «покупки».")
    def list_clear(list: str, ctx: Context) -> str:
        title = lists.list_title(list)
        if not title:
            return lists.NO_NAME
        lists.save(root_of(ctx, data_dir), title, [])
        return f"Список «{title}» очищен."


def _register_read(server: MCPServer, data_dir: Path) -> None:
    """Инструменты чтения: показать список, какие списки есть."""

    @server.tool(description="Показать пункты списка по порядку. Пример: список «покупки».")
    def list_show(list: str, ctx: Context) -> str:
        title = lists.list_title(list)
        if not title:
            return lists.NO_NAME
        items = lists.load(root_of(ctx, data_dir), title)
        if not items:
            return f"Список «{title}» пуст."
        return f"В списке «{title}»: {', '.join(items)}."

    @server.tool(name="lists", description="Какие списки есть.")
    def lists_all(ctx: Context) -> str:
        found = lists.names(root_of(ctx, data_dir))
        return f"Списки: {', '.join(found)}." if found else "Списков пока нет."
