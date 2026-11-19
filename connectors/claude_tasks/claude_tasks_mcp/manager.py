"""Задачи для Claude Code: запуск в фоне, предел одновременных и времени, отмена, журнал.

Всё меняется только из цикла событий (инструменты — `async def`), поэтому без блокировок.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from claude_tasks_mcp import phrases
from claude_tasks_mcp.record import Status, TaskRecord
from claude_tasks_mcp.runner import Runner, RunResult
from claude_tasks_mcp.speech import summarize
from claude_tasks_mcp.store import Store, person_folder

RESULT_SENTENCES = 3
INTERRUPTED_RESTART = "прервана перезапуском коннектора"
INTERRUPTED_STOP = "прервана остановкой коннектора"
INTERNAL_FAILURE = "сбой коннектора"

Announce = Callable[[str, str | None], Awaitable[None]]

logger = logging.getLogger(__name__)


class TaskError(Exception):
    """Отказ инструмента; текст — для озвучки."""


class Manager:
    """Ведёт задачи всех людей; `announce(text, person)` — объявление о конце задачи."""

    def __init__(
        self,
        store: Store,
        runner: Runner,
        announce: Announce,
        *,
        timeout_s: float,
        max_running: int,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._runner = runner
        self._announce = announce
        self._timeout_s = timeout_s
        self._max_running = max_running
        self._now = now
        self._records: dict[str, list[TaskRecord]] = {}
        self._running: dict[str, asyncio.Task[None]] = {}

    def load(self) -> None:
        """Читает журнал; задачи, оставшиеся «идущими» с прошлого запуска, — прерваны."""
        touched: dict[str, str | None] = {}
        for record in self._store.load_all():
            key = person_folder(record.person)
            if record.status == "running":
                self._close(record, "failed", error=INTERRUPTED_RESTART)
                touched[key] = record.person
            self._records.setdefault(key, []).append(record)
        for person in touched.values():
            self._save(person)

    def start(self, person: str | None, prompt: str, folder: str, path: Path) -> TaskRecord:
        """Запускает задачу `prompt` в папке `path` (`folder` — подпись); отказ — TaskError."""
        if len(self._running) >= self._max_running:
            raise TaskError(phrases.busy_text(self._max_running))
        records = self._records.setdefault(person_folder(person), [])
        name = phrases.unique_name(phrases.make_name(prompt), [r.name for r in records])
        record = TaskRecord(uuid.uuid4().hex[:12], name, prompt, folder, person, "running", self._now())
        records.append(record)
        self._save(person)
        self._running[record.id] = asyncio.create_task(self._run(record, path))
        return record

    def recent(self, person: str | None, count: int) -> list[TaskRecord]:
        """Последние `count` задач человека, новые первыми."""
        return list(reversed(self._records.get(person_folder(person), [])))[:count]

    def find(self, person: str | None, name: str) -> TaskRecord:
        """Задача по имени (без регистра; можно часть имени); пусто — последняя."""
        records = self.recent(person, len(self._records.get(person_folder(person), [])))
        if not records:
            raise TaskError(phrases.NO_TASKS)
        asked = name.strip().casefold()
        if not asked:
            return records[0]
        exact = [r for r in records if r.name.casefold() == asked]
        if exact:
            return exact[0]
        partial = [r for r in records if asked in r.name.casefold()]
        if len(partial) == 1:
            return partial[0]
        if partial:
            raise TaskError(phrases.ambiguous_text([r.name for r in partial[:3]]))
        raise TaskError(f"Задачи «{name.strip()}» нет.")

    def cancel(self, person: str | None, name: str) -> tuple[TaskRecord, bool]:
        """Отменяет задачу; возвращает (задача, шла ли она)."""
        record = self.find(person, name)
        task = self._running.get(record.id)
        if record.status != "running" or task is None:
            return record, False
        self._close(record, "cancelled")
        self._save(record.person)
        task.cancel()
        return record, True

    async def aclose(self) -> None:
        """Останавливает все идущие задачи (коннектор завершается)."""
        tasks = list(self._running.values())
        for records in self._records.values():
            for record in records:
                if record.id in self._running and record.status == "running":
                    self._close(record, "failed", error=INTERRUPTED_STOP)
                    self._save(record.person)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _close(self, record: TaskRecord, status: Status, error: str = "") -> None:
        record.status = status
        record.finished = self._now()
        record.error = error

    def _save(self, person: str | None) -> None:
        key = person_folder(person)
        self._records[key] = self._store.save(person, self._records.get(key, []))

    async def _run(self, record: TaskRecord, path: Path) -> None:
        try:
            try:
                async with asyncio.timeout(self._timeout_s):
                    result = await self._runner(record.prompt, path)
            except TimeoutError:
                result = RunResult(False, phrases.timeout_reason(self._timeout_s))
            except Exception:
                logger.exception("сбой задачи %s", record.id)
                result = RunResult(False, INTERNAL_FAILURE)
            await self._finish(record, result)
        finally:
            self._running.pop(record.id, None)

    async def _finish(self, record: TaskRecord, result: RunResult) -> None:
        if record.status != "running":
            return  # уже отменена или прервана
        if result.ok:
            self._close(record, "done")
            record.summary = summarize(result.text, RESULT_SENTENCES)
            text = phrases.done_announce(record, result.text)
        else:
            self._close(record, "failed", error=result.text)
            text = phrases.failed_text(record)
        try:
            if result.ok:
                self._store.save_output(record, result.text)
            self._save(record.person)
        except OSError:
            # Объявить важнее, чем записать: сбой диска только в журнал коннектора.
            logger.exception("не удалось записать итог задачи %s", record.id)
        try:
            await self._announce(text, record.person)
        except Exception:
            logger.exception("не удалось объявить итог задачи %s", record.id)
