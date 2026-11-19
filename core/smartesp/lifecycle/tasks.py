"""Фоновые задачи ядра: отмена с ожиданием и громкая запись о падении."""

from __future__ import annotations

import asyncio
import logging

_log = logging.getLogger("smartesp")


async def cancel_tasks(*tasks: asyncio.Task[None] | None) -> None:
    """Отменяет запущенные задачи (None пропускает) и ждёт их конца; исключения глотает."""
    started = [task for task in tasks if task is not None]
    for task in started:
        task.cancel()
    await asyncio.gather(*started, return_exceptions=True)


def log_crash(task: asyncio.Task[None]) -> None:
    """Фоновая задача ядра упала — громко в журнал (её не должно завершать ничто, кроме отмены)."""
    if not task.cancelled() and task.exception() is not None:
        _log.critical("Задача %s упала", task.get_name(), exc_info=task.exception())
