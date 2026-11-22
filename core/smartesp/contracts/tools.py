"""Договор: инструменты коннекторов (MCP-хаб) для исполнителей."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .executor import ToolSpec

ConnectorStateName = Literal["starting", "ready", "failed", "disabled"]
# mcp — коннектор с инструментами (MCP stdio); client — отдельная программа-клиент ядра (бот Telegram):
# ядро её запускает и держит, она ходит в API ядра (адрес и токен — в окружении)
ConnectorKind = Literal["mcp", "client"]


@dataclass(frozen=True)
class Suggestion:
    """Предложение клиента дописать значение в объявленную настройку-список (key): «Добавить».

    value — элемент списка («123456789=Аня»); text — что показать человеку.
    """

    key: str
    value: str
    text: str


ToolPhase = Literal["started", "finished"]


@dataclass(frozen=True)
class ConnectorState:
    """Состояние коннектора для интерфейса.

    tools — имена инструментов, как их видит модель (только у готового);
    error — текст последней ошибки (пусто, если её нет); kind — коннектор или клиент;
    log — последние строки журнала клиента; suggestions — его предложения «Добавить».
    """

    id: str
    name: str
    state: ConnectorStateName
    tools: tuple[str, ...] = ()
    error: str = ""
    kind: ConnectorKind = "mcp"
    log: tuple[str, ...] = ()
    suggestions: tuple[Suggestion, ...] = ()


@dataclass(frozen=True)
class CallContext:
    """Кто и откуда просит в текущем ходе: человек (None — неизвестно) и колонка ("" — не с колонки).

    Скилл получает их в `_meta` вызова (person — постоянный id, person_name — имя, device) — например,
    «сделай погромче» без названия колонки значит ту, с которой говорят. Скиллы раскладывают данные
    по person: переименование человека ничего у них не меняет.
    """

    person: str | None = None  # постоянный id: человек из «Людей» или "<канал>:<аккаунт>"
    device_id: str = ""
    person_name: str = ""  # имя для показа и речи (в _meta.person_name)


# Канал контекста хода (не логика): ход ставит его перед ответом исполнителя, хаб читает при вызове
# скилла. Задачи asyncio, начатые в ходе (запоздавший ответ), получают его копию.
CALL_CONTEXT: ContextVar[CallContext | None] = ContextVar("smartesp_call_context", default=None)


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
