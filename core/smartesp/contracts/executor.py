"""Договор: исполнитель запроса (модель, агент и т. п.)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


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
