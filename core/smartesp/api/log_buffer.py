"""Журнал для интерфейса: последние строки в памяти и живая рассылка подписчикам.

Обработчик ставится на корневой журнал рядом с консолью и core.log. Записи приходят
из любого потока (пул, библиотеки), а очереди подписчиков живут в цикле asyncio,
поэтому строка кладётся в очередь через call_soon_threadsafe. У каждого подписчика
очередь ограничена: медленный клиент теряет самые старые строки, а память не растёт.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass

from .redact import HideToken, hide_token

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
RECENT_LINES = 500  # столько последних строк получает новый подписчик
QUEUE_LINES = 1000  # очередь подписчика; переполнилась — выбрасываются самые старые
MAX_TEXT = 8000  # длиннее (огромный traceback) — середина вырезается: конец с текстом ошибки остаётся
CUT = "\n…\n"


@dataclass(frozen=True)
class LogLine:
    """Строка журнала: время (time.time()), уровень (INFO, WARNING…), текст целиком."""

    at: float
    level: str
    text: str


def _shorten(text: str) -> str:
    """Начало и конец длинной строки; середина — «…»."""
    if len(text) <= MAX_TEXT:
        return text
    half = (MAX_TEXT - len(CUT)) // 2
    return text[:half] + CUT + text[-half:]


class LogSubscription:
    """Подписка на новые строки; закрыть через aclose() (повторно — можно)."""

    def __init__(self, buffer: LogBuffer, size: int) -> None:
        self._buffer = buffer
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[LogLine] = asyncio.Queue(maxsize=size)
        self.dropped = 0  # сколько строк выброшено из-за переполнения

    def offer(self, line: LogLine) -> None:
        """Кладёт строку в очередь из любого потока; цикл закрыт — строка пропадает."""
        try:
            self._loop.call_soon_threadsafe(self._put, line)
        except RuntimeError:
            pass

    def _put(self, line: LogLine) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(line)

    async def get(self) -> LogLine:
        """Ждёт следующую строку."""
        return await self._queue.get()

    async def aclose(self) -> None:
        """Снимает подписку."""
        self._buffer.unsubscribe(self)


class LogBuffer(logging.Handler):
    """Обработчик журнала: помнит последние строки и рассылает новые подписчикам.

    Токен из `?token=` прячется своим фильтром (как у консоли и файла).
    """

    def __init__(self, recent: int = RECENT_LINES, queue_size: int = QUEUE_LINES) -> None:
        """recent — сколько строк помнить; queue_size — очередь каждого подписчика."""
        if recent <= 0 or queue_size <= 0:
            raise ValueError("recent и queue_size должны быть больше нуля")
        super().__init__()
        self.setFormatter(logging.Formatter(LOG_FORMAT))
        self.addFilter(HideToken())
        self._recent: deque[LogLine] = deque(maxlen=recent)
        self._queue_size = queue_size
        self._subscribers: set[LogSubscription] = set()
        self._guard = threading.Lock()  # строки и подписчики: записи идут из разных потоков

    @property
    def subscriber_count(self) -> int:
        """Число открытых подписок."""
        return len(self._subscribers)

    def emit(self, record: logging.LogRecord) -> None:
        """Запоминает строку и раздаёт подписчикам (из любого потока)."""
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 — кривая запись не должна ронять журнал
            self.handleError(record)
            return
        line = LogLine(record.created, record.levelname, _shorten(hide_token(text)))
        with self._guard:
            self._recent.append(line)
            for subscriber in self._subscribers:
                subscriber.offer(line)

    def subscribe(self) -> tuple[list[LogLine], LogSubscription]:
        """Последние строки и подписка на новые — без пропусков и повторов между ними.

        Вызывать из работающего цикла asyncio; подписку закрыть через aclose().
        """
        subscription = LogSubscription(self, self._queue_size)
        with self._guard:
            recent = list(self._recent)
            self._subscribers.add(subscription)
        return recent, subscription

    def unsubscribe(self, subscription: LogSubscription) -> None:
        """Снимает подписку; повторно — ничего не делает."""
        with self._guard:
            self._subscribers.discard(subscription)
