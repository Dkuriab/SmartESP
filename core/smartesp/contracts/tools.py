"""Договор: инструменты коннекторов (MCP-хаб) для исполнителей."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .executor import ToolSpec

ConnectorStateName = Literal["starting", "ready", "failed", "disabled"]


@dataclass(frozen=True)
class ConnectorState:
    """Состояние коннектора для интерфейса.

    tools — имена инструментов, как их видит модель (только у готового);
    error — текст последней ошибки (пусто, если её нет).
    """

    id: str
    name: str
    state: ConnectorStateName
    tools: tuple[str, ...] = ()
    error: str = ""


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
