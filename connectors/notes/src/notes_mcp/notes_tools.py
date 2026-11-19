"""Инструменты заметок."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer

from . import notes
from .context import root_of


def register(server: MCPServer, data_dir: Path, now: Callable[[], datetime]) -> None:
    """Регистрирует инструменты заметок на сервере."""

    @server.tool(description="Записать заметку с датой. Пример: «ключи лежат в ящике».")
    def note_add(text: str, ctx: Context) -> str:
        if not text.strip():
            return "Пустую заметку не записываю."
        notes.add(root_of(ctx, data_dir), text, now())
        return "Записала."

    @server.tool(description="Найти заметки по слову или фразе (до 5 последних). Пример: «ключи».")
    def notes_find(query: str, ctx: Context) -> str:
        found = notes.find(root_of(ctx, data_dir), query)[: notes.MAX_FOUND]
        if not found:
            return f"Заметок про «{query}» не нашла."
        return "Нашла: " + "; ".join(n.label() for n in found) + "."

    @server.tool(description="Удалить заметку по слову или фразе. Удаляет, только если подходит одна.")
    def note_delete(query: str, ctx: Context) -> str:
        root = root_of(ctx, data_dir)
        found = notes.find(root, query)
        if not found:
            return f"Заметок про «{query}» не нашла."
        if len(found) > 1:
            variants = "; ".join(n.text for n in found[: notes.MAX_FOUND])
            return f"Нашла несколько, уточните: {variants}."
        notes.delete(root, found[0])
        return f"Удалила заметку: {found[0].text}."
