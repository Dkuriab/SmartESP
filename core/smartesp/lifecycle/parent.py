"""Слежка за родителем: приложение держит stdin ядра открытым, пока живо."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import BinaryIO

_log = logging.getLogger(__name__)
CHUNK = 4096


def watch_parent(stream: BinaryIO, on_eof: Callable[[], None]) -> threading.Thread:
    """Запускает поток-демон: читает stream до конца и затем вызывает on_eof.

    Конец потока значит, что родитель закрыл stdin или умер. on_eof вызывается
    из этого потока, поэтому должен быть потокобезопасным. Возвращает поток.
    """

    def run() -> None:
        try:
            while stream.read(CHUNK):
                pass
        except (OSError, ValueError):  # поток закрыли под нами — тоже конец
            pass
        _log.info("Родитель закрыл stdin — останавливаюсь")
        on_eof()

    thread = threading.Thread(target=run, name="parent-watch", daemon=True)
    thread.start()
    return thread
