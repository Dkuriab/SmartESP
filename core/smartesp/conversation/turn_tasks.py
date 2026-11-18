"""Задачи идущих ходов: запуск, журнал ошибок, ожидание и отмена."""

import asyncio
import logging
from collections.abc import Coroutine

_log = logging.getLogger(__name__)


class TurnTasks:
    """Набор задач идущих ходов."""

    def __init__(self) -> None:
        """Пустой набор."""
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, coro: Coroutine[object, object, None], name: str) -> None:
        """Запускает ход отдельной задачей; её ошибка (кроме отмены) пишется в журнал."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task[None]) -> None:
        """Забывает задачу хода и пишет в журнал её ошибку, если была."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _log.error("Ход %s упал", task.get_name(), exc_info=error)

    async def drain(self, timeout_s: float) -> None:
        """Ждёт идущие ходы не дольше timeout_s секунд, затем отменяет оставшиеся и дожидается их."""
        tasks = list(self._tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout_s)
        await _cancel(pending)

    async def cancel_all(self) -> None:
        """Отменяет все идущие ходы и ждёт их завершения."""
        await _cancel(self._tasks)


async def _cancel(tasks: set[asyncio.Task[None]]) -> None:
    """Отменяет задачи и ждёт их завершения, не пробрасывая их ошибки."""
    pending = list(tasks)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
