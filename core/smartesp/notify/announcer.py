"""Очередь объявлений: ядро само говорит на колонке, повторяя, пока колонка не дослушает.

На каждую заданную колонку — своя очередь и своя фоновая задача: объявления
звучат по порядку, следующее — только после итога предыдущего. Колонка
доставки: заданная, если умеет речь по инициативе; иначе последняя активная;
иначе первая подключённая с речью по инициативе (по имени); иначе ждём, пока
какая-нибудь подключится. Итог — событие turn_finished вида
"announcement"; до итога событий нет.

Колонка занята — синтеза нет: сначала вытеснение (preempt: например, файл на колонке
останавливается и не возобновляется), не освободилась — повтор через retry_s.
"""

import asyncio
import itertools
import logging
import time
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal

from smartesp.contracts import Delivery, DevicePort, EventSink, Preempt

_log = logging.getLogger(__name__)

RETRY_S = 5.0  # колонка занята или связь оборвалась — повтор через столько секунд
EXPIRE_S = 600.0  # не доставили за столько секунд от say — снимаем
MAX_SYNTH_FAILURES = 2  # синтез упал — повторяем не больше стольких раз, затем снимаем
UNSYNTHESIZED = "unsynthesized"  # итог попытки: упал синтез, а не доставка
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


_Attempt = Delivery | Literal["unsynthesized"]


class _Speech:
    """Звук одной попытки: первый кусок синтезирован до announce; помнит, если синтез упал дальше."""

    def __init__(self, first: bytes, rest: AsyncIterator[bytes]) -> None:
        """first — уже готовый первый кусок; rest — остаток потока синтеза."""
        self._first = first
        self._rest = rest
        self.failed = False

    async def stream(self) -> AsyncIterator[bytes]:
        """Весь звук: первый кусок и остаток; сбой синтеза отмечается в failed и пробрасывается."""
        try:
            yield self._first
            async for chunk in self._rest:
                yield chunk
        except Exception:
            self.failed = True
            raise
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Закрывает поток синтеза (колонка могла так и не взять звук: busy, обрыв)."""
        await _close(self._rest)


async def _close(audio: AsyncIterator[bytes]) -> None:
    """Закрывает поток синтеза, если это генератор."""
    if isinstance(audio, AsyncGenerator):
        await audio.aclose()


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
        preempt: Preempt | None = None,
    ) -> None:
        """devices — колонки; speak — синтез текста в PCM (может кинуть, если синтеза нет);
        events — куда публиковать итог; retry_s — пауза между попытками; expire_s — срок
        доставки от say (секунды); clock — часы для срока; preempt(колонка) — освободить
        занятую колонку перед объявлением (True — освободили; None — не вытеснять).
        """
        self._devices = devices
        self._speak = speak
        self._events = events
        self._retry_s = retry_s
        self._expire_s = expire_s
        self._clock = clock
        self._preempt = preempt
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
        """Пробует, пока не доставлено, не перебито или не истёк срок; итог и колонка доставки.

        Синтез упал больше MAX_SYNTH_FAILURES раз — снимаем, не дожидаясь срока (это не сбой связи).
        Срок проверяется после неудачной попытки: последняя может прийти ровно к сроку, а
        ожидание чужого объявления на той же колонке сроком не ограничено.
        """
        device_id = item.target
        failures = 0  # сбои синтеза
        while True:
            chosen = self._choose(item.target)
            if chosen is not None:
                device_id = chosen
                result = await self._attempt(chosen, item.text)
                if result == "delivered" or result == "interrupted":
                    return await self._heard(chosen, item.text, result), chosen
                failures += result == UNSYNTHESIZED
                if failures > MAX_SYNTH_FAILURES:
                    _log.warning("Объявление a%s снято: синтез речи не удался", item.number)
                    return "undelivered", chosen
            left = item.since + self._expire_s - self._clock()
            if left <= 0:
                _log.warning("Объявление a%s не доставлено за %.0f с", item.number, self._expire_s)
                return "undelivered", device_id
            await asyncio.sleep(min(self._retry_s, left))

    def _choose(self, target: str) -> str | None:
        """Колонка доставки (с речью по инициативе): заданная, иначе последняя активная,
        иначе первая подключённая по имени (после старта ядра могли ещё не говорить)."""
        if self._devices.supports_proactive(target):
            return target
        last = self._devices.last_active_device()
        if last is not None and self._devices.supports_proactive(last):
            return last
        connected = self._devices.proactive_devices()
        return connected[0] if connected else None

    async def _attempt(self, device_id: str, text: str) -> _Attempt:
        """Одна попытка: первый кусок синтеза, затем announce.

        Колонка занята и вытеснить нечего — "busy" без синтеза.
        Синтез упал (сразу или посреди звука) — UNSYNTHESIZED; до первого куска колонка
        ничего не получает (нет и announce, значит, и сигнала «внимание»). Голоса ещё нет (speak кинул сразу)
        или сбой колонки — "lost".
        """
        async with self._speaking.setdefault(device_id, asyncio.Lock()):
            if self._devices.is_busy(device_id) and not await self._free(device_id):
                return "busy"  # синтезировать незачем: повтор через retry_s
            speech: _Speech | None = None
            try:
                speech = await self._synthesize(text)
                result: _Attempt = UNSYNTHESIZED
                if speech is not None:
                    result = await self._devices.announce(device_id, speech.stream())
            except Exception:
                _log.warning("Объявление на %s не удалось", device_id, exc_info=True)
                result = "lost"
            finally:
                if speech is not None:
                    await speech.aclose()
        if speech is not None and speech.failed and result == "lost":
            return UNSYNTHESIZED
        return result

    async def _free(self, device_id: str) -> bool:
        """Вытесняет то, что занимает колонку (preempt); True — колонку освободили."""
        if self._preempt is None:
            return False
        try:
            return await self._preempt(device_id)
        except Exception:
            _log.warning("Вытеснение на %s перед объявлением не удалось", device_id, exc_info=True)
            return False

    async def _synthesize(self, text: str) -> _Speech | None:
        """Синтезирует первый кусок звука; синтез упал или звука нет — None (в журнал)."""
        audio = self._speak(text)
        try:
            first = await anext(audio)
        except Exception:  # и StopAsyncIteration: пустой звук объявлять нечего
            _log.warning("Синтез объявления не удался", exc_info=True)
            await _close(audio)
            return None
        return _Speech(first, audio)

    async def _heard(self, device_id: str, text: str, result: Delivery) -> str:
        """Итог услышанного объявления; доиграно и кончилось вопросом — включаем микрофон."""
        if result != "delivered":
            return "interrupted"  # перебили сознательно — считаем услышанным
        if self._listen_after and _is_question(text):
            try:
                await self._devices.listen(device_id)
            except Exception:  # объявление уже услышано
                _log.warning("listen на %s после объявления не удался", device_id, exc_info=True)
        return "ok"

    def _publish(self, item: _Item, status: str, device_id: str) -> None:
        """Событие turn_finished объявления: ok, interrupted или undelivered."""
        if self._events is not None:
            try:  # сбой ленты не должен ронять очередь
                self._events.publish("turn_finished", _event(item, status, device_id, self._devices))
            except Exception:
                _log.error("Событие объявления a%s не опубликовано", item.number, exc_info=True)


def _event(item: _Item, status: str, device_id: str, devices: DevicePort) -> dict[str, object]:
    """Данные turn_finished объявления."""
    return {
        "turn_id": f"a{item.number}",
        "device_id": device_id,
        "device_name": devices.device_name(device_id),
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
    }


def _log_crash(task: asyncio.Task[None]) -> None:
    """Задача очереди упала (не должна) — в журнал."""
    if not task.cancelled() and task.exception() is not None:
        _log.error("Очередь объявлений %s упала", task.get_name(), exc_info=task.exception())
