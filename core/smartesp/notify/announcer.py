"""Очередь объявлений: ядро само говорит на колонке, повторяя, пока колонка не дослушает.

На каждую заданную колонку — своя очередь и своя фоновая задача: объявления
звучат по порядку, следующее — только после итога предыдущего. Колонка
доставки: заданная, если умеет речь по инициативе; иначе последняя активная;
иначе ждём, пока одна из них подключится. Итог — событие turn_finished вида
"announcement"; до итога событий нет.
"""

import asyncio
import itertools
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from smartesp.contracts import Delivery, DevicePort, EventSink

_log = logging.getLogger(__name__)

RETRY_S = 5.0  # колонка занята или связь оборвалась — повтор через столько секунд
EXPIRE_S = 600.0  # не доставили за столько секунд от say — снимаем
STYLE = "normal"  # объявления звучат стилем по умолчанию
_CLOSERS = " \t\n\"'»“”)!.…"  # кавычки, скобки и «!», «.» после «?» («Правда?!», «Что?..»)


@dataclass(frozen=True)
class _Item:
    """Объявление в очереди: номер, заданная колонка, текст, кто говорит и когда поставлено."""

    number: int
    target: str
    text: str
    source: str
    since: float


def _is_question(text: str) -> bool:
    """True, если текст кончается вопросом (Кузя ждёт ответа)."""
    return text.rstrip(_CLOSERS).endswith("?")


class Announcer:
    """Очередь объявлений по колонкам с повторами; реализует contracts.Announcer."""

    def __init__(
        self,
        devices: DevicePort,
        speak: Callable[[str], AsyncIterator[bytes]],
        *,
        events: EventSink | None,
        retry_s: float = RETRY_S,
        expire_s: float = EXPIRE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """devices — колонки; speak — синтез текста в PCM (может кинуть, если синтеза нет);
        events — куда публиковать итог; retry_s — пауза между попытками; expire_s — срок
        доставки от say (секунды); clock — часы для срока.
        """
        self._devices = devices
        self._speak = speak
        self._events = events
        self._retry_s = retry_s
        self._expire_s = expire_s
        self._clock = clock
        self._numbers = itertools.count(1)
        self._queues: dict[str, deque[_Item]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._speaking: dict[str, asyncio.Lock] = {}  # одна доставка на колонку
        self._listen_after = True
        self._closed = False

    def say(self, device_id: str, text: str, source: str) -> None:
        """Ставит text в очередь колонки device_id; source — кто говорит (для ленты).

        Не ждёт доставки. После aclose ничего не делает.
        """
        if self._closed:
            _log.warning("Объявление для %s после остановки отброшено", device_id)
            return
        item = _Item(next(self._numbers), device_id, text, source, self._clock())
        self._queues.setdefault(device_id, deque()).append(item)
        if device_id not in self._workers:
            worker = asyncio.create_task(self._drain(device_id), name=f"announcer {device_id}")
            self._workers[device_id] = worker
            worker.add_done_callback(_log_crash)

    def set_listen_after(self, on: bool) -> None:
        """Включает или выключает микрофон колонке после доставленного объявления-вопроса."""
        self._listen_after = on

    async def aclose(self) -> None:
        """Отменяет доставки и бросает очереди; дальше say ничего не делает. Повтор безопасен."""
        self._closed = True
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        self._workers.clear()
        self._queues.clear()

    # ---- внутреннее ----

    async def _drain(self, target: str) -> None:
        """Доставляет объявления колонки target по порядку, пока очередь не опустеет."""
        queue = self._queues[target]
        try:
            while queue:
                item = queue.popleft()
                try:
                    status, device_id = await self._deliver(item)
                except Exception:
                    _log.error("Объявление a%s: сбой доставки", item.number, exc_info=True)
                    status, device_id = "undelivered", item.target
                self._publish(item, status, device_id)
        finally:
            self._workers.pop(target, None)
            if not queue:
                self._queues.pop(target, None)

    async def _deliver(self, item: _Item) -> tuple[str, str]:
        """Пробует, пока не доставлено, не перебито или не истёк срок; итог и колонка доставки."""
        device_id = item.target
        while True:
            chosen = self._choose(item.target)
            if chosen is not None:
                device_id = chosen
                result = await self._attempt(chosen, item.text)
                if result == "delivered":
                    await self._listen(chosen, item.text)
                    return "ok", chosen
                if result == "interrupted":  # перебили сознательно — считаем услышанным
                    return "interrupted", chosen
            left = item.since + self._expire_s - self._clock()
            if left <= 0:
                _log.warning("Объявление a%s не доставлено за %.0f с", item.number, self._expire_s)
                return "undelivered", device_id
            await asyncio.sleep(min(self._retry_s, left))

    def _choose(self, target: str) -> str | None:
        """Колонка доставки: заданная, иначе последняя активная (обе — с речью по инициативе)."""
        if self._devices.supports_proactive(target):
            return target
        last = self._devices.last_active_device()
        if last is not None and self._devices.supports_proactive(last):
            return last
        return None

    async def _attempt(self, device_id: str, text: str) -> Delivery:
        """Одна попытка: синтез и announce; сбой синтеза или колонки — "lost" (повторим)."""
        lock = self._speaking.setdefault(device_id, asyncio.Lock())
        async with lock:
            try:
                return await self._devices.announce(device_id, self._speak(text))
            except Exception:
                _log.warning("Объявление на %s не удалось", device_id, exc_info=True)
                return "lost"

    async def _listen(self, device_id: str, text: str) -> None:
        """Объявление кончилось вопросом — включаем колонке микрофон (если так настроено)."""
        if self._listen_after and _is_question(text):
            await self._devices.listen(device_id)

    def _publish(self, item: _Item, status: str, device_id: str) -> None:
        """Событие turn_finished объявления: ok, interrupted или undelivered."""
        if self._events is None:
            return
        self._events.publish(
            "turn_finished",
            {
                "turn_id": f"a{item.number}",
                "device_id": device_id,
                "device_name": self._devices.device_name(device_id),
                "at": time.time(),
                "text": "",
                "annotations": [],
                "style": STYLE,
                "answer": item.text,
                "status": status,
                "path": [item.source],
                "delegations": [],
                "origin": "core",
                "kind": "announcement",
            },
        )


def _log_crash(task: asyncio.Task[None]) -> None:
    """Задача очереди упала (не должна) — в журнал."""
    if not task.cancelled() and task.exception() is not None:
        _log.error("Очередь объявлений %s упала", task.get_name(), exc_info=task.exception())
