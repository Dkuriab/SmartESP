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
    label: str = ""  # как показать источник в промпте («[время]»); пусто — имя источника


class Stage(Protocol):
    """Обработчик: смотрит на реплику и возвращает пометки."""

    name: str
    # Правило для системного промпта входного исполнителя: как понимать пометки
    # этого обработчика. Пустая строка — правила нет. Ядро добавляет правила
    # включённых обработчиков само, в настройках их писать не нужно.
    prompt_hint: str

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Анализирует реплику и возвращает список пометок."""
        ...


# «Прогнать все обработчики» разом.
Analyzer = Callable[[Utterance], Awaitable[list[Annotation]]]
