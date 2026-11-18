"""Договор: обработчики реплики (этапы анализа)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from .audio import Utterance


@dataclass(frozen=True)
class Annotation:
    """Пометка обработчика о реплике."""

    text: str  # строка для промпта
    source: str  # имя обработчика
    data: dict[str, object] = field(default_factory=lambda: dict[str, object]())


class Stage(Protocol):
    """Обработчик: смотрит на реплику и возвращает пометки."""

    name: str

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Анализирует реплику и возвращает список пометок."""
        ...


# «Прогнать все обработчики» разом.
Analyzer = Callable[[Utterance], Awaitable[list[Annotation]]]
