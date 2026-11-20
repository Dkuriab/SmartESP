"""Договор: задачи «В работе» — отложенные дела ядра и коннекторов, которые идут сейчас."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

# Состояние задачи: идёт; готово; не удалось; отменена (или её источник пропал).
TaskStatus = Literal["running", "done", "failed", "cancelled"]


@dataclass(frozen=True)
class TaskReport:
    """Сообщение источника о задаче: новая, изменилась или закончилась.

    source — кто ведёт задачу ("late_answer", "connector:<id>"); id — уникален в пределах
    source; title — что делается (пусто в обновлении — прежнее); eta — когда ожидается конец
    (time.time(); None — неизвестно или прежнее); device_id — колонка задачи (пусто — нет);
    person — чья задача (пусто — дом или неизвестно); result — короткий итог законченной.
    """

    source: str
    id: str
    title: str = ""
    status: TaskStatus = "running"
    eta: float | None = None
    device_id: str = ""
    person: str = ""
    result: str = ""


@dataclass(frozen=True)
class TaskInfo:
    """Задача в реестре для интерфейса: key — "<source>/<id>"; времена — time.time()."""

    key: str
    source: str
    id: str
    title: str
    status: TaskStatus
    started_at: float
    eta: float | None
    finished_at: float | None
    device_id: str
    device_name: str
    person: str
    result: str


class TaskBoard(Protocol):
    """Реестр «В работе» (реализует модуль tasks): источники сообщают, интерфейс читает."""

    def report(self, report: TaskReport) -> None:
        """Принимает сообщение о задаче без ожидания; неверное — в журнал, без исключений."""
        ...

    def forget(self, source: str) -> None:
        """Источник пропал (коннектор упал или убран): его идущие задачи — отменены."""
        ...

    def tasks(self) -> list[TaskInfo]:
        """Идущие задачи (старые первыми), затем недавно законченные (новые первыми)."""
        ...
