"""Договор: исполнитель запроса (модель, агент и т. п.)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    """Сообщение диалога."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ReplyPart:
    """Кусок ответа (пока только текст)."""

    text: str


class ExecutorError(Exception):
    """Исполнитель недоступен (нет сервера или модели)."""


class Executor(Protocol):
    """Исполнитель: по сообщениям выдаёт ответ по кускам."""

    def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        """Выполняет запрос и отдаёт куски ответа."""
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
