"""Договор: исполнитель запроса (модель, агент и т. п.)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

DELEGATE_TOOL = "delegate"  # имя инструмента передачи задачи другому исполнителю


@dataclass(frozen=True)
class ChatMessage:
    """Сообщение диалога.

    tool_calls — вызовы инструментов в сообщении assistant; tool_name — имя
    инструмента в сообщении tool (результат его вызова).
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str = ""


@dataclass(frozen=True)
class ToolSpec:
    """Описание инструмента, который исполнитель может вызвать."""

    name: str
    description: str
    parameters: dict[str, object]  # JSON Schema параметров


@dataclass(frozen=True)
class ToolCall:
    """Вызов инструмента, выбранный моделью."""

    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class Handoff:
    """Передача задачи от одного исполнителя другому."""

    source: str  # id передающего исполнителя
    target: str  # id принимающего
    target_name: str  # имя принимающего (для озвучки и интерфейса)
    task: str  # задача своими словами
    auto: bool = False  # передача по фразе без вызова инструмента


@dataclass(frozen=True)
class ReplyPart:
    """Кусок ответа: текст, вызов инструмента или передача задачи.

    failure — служебная фраза об ошибке: она звучит, а ход помечается ошибкой.
    """

    text: str = ""
    tool_call: ToolCall | None = None
    handoff: Handoff | None = None
    failure: bool = False


class ExecutorError(Exception):
    """Исполнитель недоступен (нет сервера или модели)."""


class ModelNotLoadedError(Exception):
    """Модели нет среди загруженных в память Ollama: выгружать нечего."""


class Executor(Protocol):
    """Исполнитель: по сообщениям выдаёт ответ по кускам."""

    def run(self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()) -> AsyncIterator[ReplyPart]:
        """Выполняет запрос и отдаёт куски ответа; tools — доступные инструменты."""
        ...


@runtime_checkable
class WarmsUp(Protocol):
    """Необязательная способность части: загрузиться заранее (прогрев модели)."""

    async def warm_up(self) -> None:
        """Загружает модель в память; ошибка — исключение."""
        ...


@runtime_checkable
class Unloads(Protocol):
    """Необязательная способность исполнителя: выгрузить свою модель из памяти."""

    model: str

    async def unload(self, timeout_s: float = 1.0) -> None:
        """Выгружает модель, ждёт не дольше timeout_s секунд; не бросает исключений."""
        ...


@runtime_checkable
class Identified(Protocol):
    """Необязательная способность исполнителя: знает свой id из настроек."""

    id: str


@runtime_checkable
class UsesModels(Protocol):
    """Необязательная способность исполнителя: использует модели Ollama."""

    def models(self) -> frozenset[str]:
        """Имена моделей, которые держит исполнитель."""
        ...

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        """Выгружает названные модели, ждёт не дольше timeout_s секунд; не бросает исключений."""
        ...
