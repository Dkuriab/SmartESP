"""Слежка за родителем: приложение держит stdin ядра открытым, пока живо."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

_log = logging.getLogger(__name__)
CHUNK = 4096


def watch_parent(fd: int, on_eof: Callable[[], None]) -> threading.Thread:
    """Запускает поток-демон: читает файловый дескриптор fd до конца и затем вызывает on_eof.

    Конец потока значит, что родитель закрыл stdin или умер. Читается сам дескриптор
    (os.read), а не sys.stdin.buffer: висящее чтение буфера держит его блокировку, и
    интерпретатор падает при выходе. on_eof вызывается из этого потока, поэтому
    должен быть потокобезопасным. Возвращает поток.
    """

    def run() -> None:
        try:
            while os.read(fd, CHUNK):
                pass
        except OSError:  # дескриптор закрыли под нами — тоже конец
            pass
        _log.info("Родитель закрыл stdin — останавливаюсь")
        on_eof()

    thread = threading.Thread(target=run, name="parent-watch", daemon=True)
    thread.start()
    return thread
