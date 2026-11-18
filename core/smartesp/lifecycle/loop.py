"""Цикл asyncio процесса ядра без ожидания потоков пула при выходе."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_loop[T](main: Coroutine[Any, Any, T]) -> T:
    """Как asyncio.run, но не ждёт потоков пула по умолчанию.

    asyncio.run при выходе ждёт потоки asyncio.to_thread (до 5 минут): зависшее
    скачивание модели держало бы процесс после остановки. Здесь оставшиеся задачи
    отменяются, а пул закрывается без ожидания. Поток, который ещё работает, не даст
    интерпретатору выйти сам — поэтому после run_loop процесс завершают os._exit/execv.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(main)
    finally:
        try:
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()  # пул закрывается с wait=False


def exit_code(error: BaseException) -> int:
    """Код выхода процесса для исключения, вылетевшего из run_loop.

    SystemExit — его код (None — 0, текст — 1); любое другое исключение — 1.
    """
    if not isinstance(error, SystemExit):
        return 1
    if error.code is None or isinstance(error.code, int):
        return error.code or 0
    return 1
