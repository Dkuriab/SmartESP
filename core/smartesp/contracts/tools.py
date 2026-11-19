"""Договор: инструменты коннекторов (MCP-хаб) для исполнителей."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .executor import ToolSpec


@dataclass(frozen=True)
class ToolResult:
    """Итог вызова инструмента: текст для модели и признак ошибки."""

    text: str
    is_error: bool = False


class ToolBox(Protocol):
    """Инструменты всех готовых коннекторов; реализует McpHub."""

    def specs(self) -> list[ToolSpec]:
        """Возвращает описания инструментов готовых коннекторов (имена уникальны)."""
        ...

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        """Вызывает инструмент name с аргументами; person — кто просит (None — неизвестно).

        Не бросает исключений: ошибка, таймаут или упавший коннектор — ToolResult(is_error=True).
        """
        ...
