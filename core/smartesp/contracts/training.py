"""Договор: обучение моделей — наборы для обучения, их цели и записи фраз с колонок."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TrainTarget:
    """Цель — отдельная модель: на какие фразы откликаться (positive) и на какие нет (negative)."""

    id: str
    title: str
    positive: tuple[str, ...]
    negative: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhraseRecords:
    """Сколько записей фразы у каждого человека: {имя: число}."""

    phrase: str
    people: dict[str, int] = field(default_factory=lambda: dict[str, int]())


@dataclass(frozen=True)
class TrainKit:
    """Набор для обучения (папка trainers/<id>) с целями владельца и счётом записей по фразам."""

    id: str
    title: str
    description: str
    record_hint: str  # подсказка при записи: как говорить
    targets: tuple[TrainTarget, ...]
    phrases: tuple[PhraseRecords, ...]  # все фразы целей, в порядке появления


@dataclass(frozen=True)
class PhraseRecording:
    """Запись фразы: имя файла, длительность и пик громкости (дБ от полной шкалы)."""

    name: str
    seconds: float
    peak_db: float


class TrainingLookupError(LookupError):
    """Нет такого набора, фразы или записи."""


class RecordRefusedError(Exception):
    """Колонка не может записать сейчас: не подключена, старая прошивка или занята."""


class NothingHeardError(Exception):
    """Колонка ничего не услышала: речи не было."""


class TrainingPort(Protocol):
    """Обучение для API: наборы, цели, запись фраз с колонки, прослушивание и удаление записей."""

    def kits(self) -> list[TrainKit]:
        """Наборы для обучения с целями и счётом записей."""
        ...

    def save_targets(self, kit: str, targets: list[TrainTarget]) -> TrainKit:
        """Заменяет цели набора; неверные — ValueError, нет набора — TrainingLookupError."""
        ...

    async def record(self, kit: str, device_id: str, phrase: str, person: str) -> PhraseRecording:
        """Пишет фразу с колонки (она пикает и слушает до паузы) и сохраняет.

        Фразы нет в целях — TrainingLookupError; колонка не может — RecordRefusedError;
        речи не было — NothingHeardError.
        """
        ...

    def recordings(self, kit: str, phrase: str, person: str) -> list[PhraseRecording]:
        """Записи фразы человека, от старых к новым."""
        ...

    def recording_file(self, kit: str, phrase: str, person: str, name: str) -> Path:
        """Путь к файлу записи (WAV); нет — TrainingLookupError."""
        ...

    def delete_recording(self, kit: str, phrase: str, person: str, name: str) -> None:
        """Удаляет запись; нет — TrainingLookupError."""
        ...
