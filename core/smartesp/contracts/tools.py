"""Договор: инструменты коннекторов (MCP-хаб) для исполнителей."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .executor import ToolSpec

ConnectorStateName = Literal["starting", "ready", "failed", "disabled"]
ToolPhase = Literal["started", "finished"]


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


@dataclass(frozen=True)
class ToolUse:
    """Вызов инструмента коннектора участником сети (для живой подсветки и ленты).

    executor — id участника, вызвавшего инструмент; tool — имя, как его видит модель;
    state — начат или закончен; ok — итог (у начатого всегда True).
    У законченного ещё arguments — аргументы вызова модели и result — текст ответа
    инструмента, который получила модель (для истории хода).
    """

    executor: str
    tool: str
    state: ToolPhase
    ok: bool = True
    arguments: dict[str, object] = field(default_factory=dict[str, object])
    result: str = ""


ToolObserver = Callable[[ToolUse], None]  # получает вызовы инструментов; не должен бросать исключений


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
