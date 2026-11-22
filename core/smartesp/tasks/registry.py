"""Реестр «В работе»: что сейчас делается в фоне, для кого и когда ожидается.

Источники (запоздавшие ответы моделей, коннекторы) сообщают о задачах TaskReport;
реестр хранит их в памяти и публикует события task_started, task_updated,
task_finished. Законченная задача видна ещё keep_s секунд (интерфейс её гасит), затем уходит.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable

from smartesp.contracts import EventSink, TaskInfo, TaskReport

_log = logging.getLogger(__name__)

KEEP_S = 120.0  # столько секунд законченная задача ещё видна
MAX_TASKS = 200  # больше задач не держим: новые сверх — в журнал и мимо
TITLE_CHARS = 120
RESULT_CHARS = 300
_FINISHED = ("done", "failed", "cancelled")


def _clip(text: str, limit: int) -> str:
    """Текст без пробелов по краям, не длиннее limit (с «…»)."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _data(task: TaskInfo) -> dict[str, object]:
    """Данные события задачи."""
    return dataclasses.asdict(task)


class TaskRegistry:
    """Задачи «В работе» по ключу "<source>/<id>"; реализует contracts.TaskBoard."""

    def __init__(
        self,
        events: EventSink | None,
        device_name: Callable[[str], str] = lambda device_id: device_id,
        *,
        person_name: Callable[[str], str] = lambda person_id: person_id,
        clock: Callable[[], float] = time.time,
        keep_s: float = KEEP_S,
        max_tasks: int = MAX_TASKS,
    ) -> None:
        """events — куда публиковать; device_name — имя колонки по id; person_name — имя человека по
        постоянному id (скиллы сообщают id, интерфейсу нужно имя); clock — настенные часы."""
        self._events = events
        self._device_name = device_name
        self._person_name = person_name
        self._clock = clock
        self._keep_s = keep_s
        self._max_tasks = max_tasks
        self._tasks: dict[str, TaskInfo] = {}

    def report(self, report: TaskReport) -> None:
        """Новая задача, обновление или конец; без id или без названия у новой — в журнал."""
        self._prune()
        key = f"{report.source}/{report.id}"
        old = self._tasks.get(key)
        if old is not None and old.status != "running":
            if report.status != "running":
                return  # уже закончена: повтор конца ничего не меняет
            old = None  # снова идёт — новая задача с тем же id
        if not report.id or (old is None and not report.title.strip()):
            _log.warning("Задача %s без id или названия пропущена", key)
            return
        if old is None and not self._room():
            _log.warning("Задач больше %d: %s пропущена", self._max_tasks, key)
            return
        task = self._merge(key, old, report)
        if task == old:
            return
        self._tasks[key] = task
        self._publish(old, task)

    def forget(self, source: str) -> None:
        """Идущие задачи источника source отменяются (источник пропал)."""
        for task in list(self._tasks.values()):
            if task.source == source and task.status == "running":
                self.report(TaskReport(source, task.id, status="cancelled"))

    def tasks(self) -> list[TaskInfo]:
        """Идущие (старые первыми), затем законченные (новые первыми)."""
        self._prune()
        running = sorted(
            (t for t in self._tasks.values() if t.status == "running"), key=lambda t: t.started_at
        )
        done = [t for t in self._tasks.values() if t.status != "running"]
        done.sort(key=lambda t: t.finished_at or 0.0, reverse=True)
        return [*running, *done]

    def _merge(self, key: str, old: TaskInfo | None, report: TaskReport) -> TaskInfo:
        """Задача после сообщения: пустые поля обновления не затирают прежние."""
        now = self._clock()
        finished = report.status in _FINISHED
        device_id = report.device_id or (old.device_id if old else "")
        return TaskInfo(
            key=key,
            source=report.source,
            id=report.id,
            title=_clip(report.title, TITLE_CHARS) or (old.title if old else ""),
            status=report.status,
            started_at=old.started_at if old else now,
            eta=report.eta if report.eta is not None else (old.eta if old else None),
            finished_at=now if finished else None,
            device_id=device_id,
            device_name=self._device_name(device_id) if device_id else "",
            person=self._person_name(report.person) if report.person else (old.person if old else ""),
            result=_clip(report.result, RESULT_CHARS) or (old.result if old else ""),
        )

    def _publish(self, old: TaskInfo | None, task: TaskInfo) -> None:
        """task_started, task_updated или task_finished."""
        if task.status != "running":
            kind = "task_finished"
        else:
            kind = "task_started" if old is None else "task_updated"
        if self._events is not None:
            try:  # сбой ленты не должен ронять источник
                self._events.publish(kind, _data(task))
            except Exception:
                _log.error("Событие задачи %s не опубликовано", task.key, exc_info=True)

    def _room(self) -> bool:
        """Есть ли место для новой задачи; нет — уступает самая старая законченная."""
        if len(self._tasks) < self._max_tasks:
            return True
        done = [t for t in self._tasks.values() if t.finished_at is not None]
        if not done:
            return False
        del self._tasks[min(done, key=lambda t: t.finished_at or 0.0).key]
        return True

    def _prune(self) -> None:
        """Убирает законченные задачи старше keep_s."""
        edge = self._clock() - self._keep_s
        for key, task in list(self._tasks.items()):
            if task.finished_at is not None and task.finished_at < edge:
                del self._tasks[key]
