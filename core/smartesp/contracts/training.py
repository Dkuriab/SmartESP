"""Договор: обучение моделей — наборы для обучения, их цели и записи фраз с колонок."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


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
class TrainStep:
    """Шаг обучения набора: id, название, пояснение; per_target — шаг делается для выбранной цели."""

    id: str
    title: str
    hint: str = ""
    per_target: bool = False


JobStatus = Literal["running", "done", "failed", "cancelled"]


@dataclass(frozen=True)
class TrainJob:
    """Шаг, который идёт или шёл последним: ход (стадия, сколько из скольки), журнал, итог."""

    kit: str
    step: str
    target: str
    status: JobStatus
    started_at: float  # time.time()
    finished_at: float | None = None
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    log: tuple[str, ...] = ()  # последние строки журнала
    result: dict[str, object] | None = None


@dataclass(frozen=True)
class TrainKit:
    """Набор для обучения (папка trainers/<id>) с целями владельца и счётом записей по фразам."""

    id: str
    title: str
    description: str
    record_hint: str  # подсказка при записи: как говорить
    targets: tuple[TrainTarget, ...]
    phrases: tuple[PhraseRecords, ...]  # все фразы целей, в порядке появления
    steps: tuple[TrainStep, ...] = ()


@dataclass(frozen=True)
class PhraseRecording:
    """Запись фразы: имя файла, длительность и пик громкости (дБ от полной шкалы)."""

    name: str
    seconds: float
    peak_db: float


class TrainingLookupError(LookupError):
    """Нет такого набора, фразы или записи."""


class TrainingBusyError(Exception):
    """Уже идёт шаг обучения: одновременно — только один (обучение занимает весь процессор)."""


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

    def start_step(self, kit: str, step: str, target: str = "", run: str = "") -> TrainJob:
        """Запускает шаг набора (для цели target; run — прогон для встраивания, пусто — последний).

        Нет набора, шага или цели — TrainingLookupError; уже идёт шаг — TrainingBusyError.
        """
        ...

    async def stop_job(self) -> None:
        """Останавливает идущий шаг (если есть)."""
        ...

    def job(self, kit: str) -> TrainJob | None:
        """Идущий или последний шаг набора; не было — None."""
        ...

    def runs(self, kit: str) -> list[dict[str, object]]:
        """Итоги прогонов набора (result.json без кривой), новые первыми."""
        ...
