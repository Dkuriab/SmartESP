"""Уведомление коннектора о задаче «В работе»: `{"type": "task", "id", "title", "status", "eta"}`.

Шлётся тем же путём, что объявление: уведомлением журнала MCP в журнале «smartesp».
Поля: id — строка, уникальная у коннектора (обязательно); title — что делается
(обязательно у новой задачи); status — running | done | failed | cancelled (по умолчанию
running); eta — когда ожидается конец: число секунд Unix или строка ISO 8601 (без пояса —
местное время); person — чья задача; result — короткий итог законченной.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast, get_args

from smartesp.contracts import TaskBoard, TaskReport, TaskStatus

logger = logging.getLogger("smartesp.tools")

TASK_TYPE = "task"
SOURCE_PREFIX = "connector:"  # источник задач коннектора в реестре: "connector:<id>"
_STATUSES: tuple[str, ...] = get_args(TaskStatus)


def task_source(connector_id: str) -> str:
    """Источник задач коннектора в реестре «В работе»."""
    return SOURCE_PREFIX + connector_id


def _eta(value: object) -> float | None:
    """Срок из числа секунд Unix или строки ISO 8601; иначе ValueError."""
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        moment = datetime.fromisoformat(value)
        return (moment if moment.tzinfo else moment.astimezone()).timestamp()
    raise ValueError("eta")


def _text(fields: dict[str, Any], name: str) -> str:
    """Строковое поле или пусто; не строка — ValueError."""
    value = fields.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(name)
    return value


def parse_task(fields: dict[str, Any], connector_id: str) -> TaskReport:
    """Сообщение о задаче из полей уведомления; неверное — ValueError."""
    task_id, status = fields.get("id"), fields.get("status", "running")
    if not isinstance(task_id, str | int) or isinstance(task_id, bool) or str(task_id) == "":
        raise ValueError("id")
    if status not in _STATUSES:
        raise ValueError("status")
    return TaskReport(
        source=task_source(connector_id),
        id=str(task_id),
        title=_text(fields, "title"),
        status=cast(TaskStatus, status),
        eta=_eta(fields.get("eta")),
        person=_text(fields, "person"),
        result=_text(fields, "result"),
    )


def handle_task(fields: dict[str, Any], connector_id: str, tasks: TaskBoard | None) -> None:
    """Передаёт задачу коннектора в реестр; неверная или сбой реестра — в журнал."""
    try:
        report = parse_task(fields, connector_id)
    except ValueError:
        logger.warning("Коннектор %s: неверная задача %r", connector_id, fields)
        return
    if tasks is None:
        return
    try:
        tasks.report(report)
    except Exception:
        logger.exception("Коннектор %s: реестр задач упал", connector_id)
