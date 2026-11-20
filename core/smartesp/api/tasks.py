"""Задачи «В работе»: GET /tasks (события task_started, task_updated, task_finished — в /events)."""

from __future__ import annotations

import dataclasses
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from smartesp.contracts import TaskBoard


class TaskOut(BaseModel):
    """Задача «В работе»; те же поля — в данных событий task_*. Времена — секунды Unix."""

    key: str  # "<source>/<id>": уникален в реестре
    source: str  # кто ведёт: "late_answer" (запоздавший ответ модели), "connector:<id>"
    id: str
    title: str
    status: Literal["running", "done", "failed", "cancelled"]
    started_at: float
    eta: float | None = None  # когда ожидается конец; None — неизвестно
    finished_at: float | None = None
    device_id: str = ""  # колонка задачи; пусто — нет
    device_name: str = ""
    person: str = ""  # чья задача; пусто — дом или неизвестно
    result: str = ""  # короткий итог законченной


def add_tasks_routes(secured: APIRouter, tasks: TaskBoard | None) -> None:
    """GET /tasks: идущие задачи, затем недавно законченные; без реестра — пусто."""

    @secured.get("/tasks")
    def get_tasks() -> list[TaskOut]:
        items = tasks.tasks() if tasks is not None else []
        return [TaskOut.model_validate(dataclasses.asdict(item)) for item in items]
