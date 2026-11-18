"""Помощники менеджера голосов: ход скачивания из потока в цикл и упаковка WAV."""

import asyncio
import io
import threading
import time
import wave
from collections.abc import Callable

from smartesp.contracts import SAMPLE_RATE

# Без известного размера — не чаще 10 событий в секунду.
_MIN_INTERVAL_S = 0.1


class DownloadAbandoned(Exception):
    """Скачивание больше никому не нужно: бросается в потоке, чтобы оборвать его."""


class ProgressRelay:
    """Вызывается в потоке скачивания и передаёт ход в цикл событий.

    Прореживание: при известном размере — событие на каждый новый целый процент
    (не больше ~100 на файл), без размера — не чаще раза в 0,1 с. После stop()
    следующий вызов бросает DownloadAbandoned, и скачивание в потоке обрывается.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, emit: Callable[[int, int | None], None]) -> None:
        self._loop = loop
        self._emit = emit
        self._stopped = threading.Event()
        self._percent: int | None = None
        self._at = 0.0

    def stop(self) -> None:
        """Обрывает скачивание при следующем вызове и глушит ещё не доставленные события."""
        self._stopped.set()

    def __call__(self, done: int, total: int | None) -> None:
        if self._stopped.is_set():
            raise DownloadAbandoned
        now = time.monotonic()
        if total:
            percent = done * 100 // total
            due = percent != self._percent
        else:
            percent = None
            due = now - self._at >= _MIN_INTERVAL_S
        if not due:
            return
        self._percent, self._at = percent, now
        try:
            self._loop.call_soon_threadsafe(self._deliver, done, total)
        except RuntimeError as exc:  # цикл уже закрыт
            raise DownloadAbandoned from exc

    def _deliver(self, done: int, total: int | None) -> None:
        if not self._stopped.is_set():
            self._emit(done, total)


def to_wav(pcm: bytes) -> bytes:
    """Заворачивает PCM 16 кГц s16le моно в WAV-файл."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)
    return buf.getvalue()
