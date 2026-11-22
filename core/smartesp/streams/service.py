"""Потоки на колонках (реализует SpeakerStreams): очереди, выбор колонки, ссылки, отчёты колонок.

Колонка тянет звук сама: команда stream_start с одноразовой ссылкой /device/stream/<токен>, звук —
open(токен). По отчётам stream_status ядро ведёт позицию, по ended переходит к следующему, по
failed пропускает сломанный (три подряд — стоп с ошибкой). Колонка не отчиталась о потоке за
start_timeout_s — стоп с ошибкой. Переходы — в runner.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from dataclasses import asdict

from smartesp.contracts import (
    DeviceInfo,
    EventSink,
    StreamAction,
    StreamCommand,
    StreamInfo,
    StreamItem,
    StreamLink,
    StreamPhase,
    StreamRefused,
    StreamReport,
)

from . import texts
from .capture import Probe
from .pick import check_items, pick_for_control, pick_for_play
from .queue import SpeakerQueue
from .runner import Runner
from .sources import FIRST_CHUNK_S, Decode

_log = logging.getLogger(__name__)

START_TIMEOUT_S = 20.0
STOP_WAIT_S = 1.5  # пауза ждёт отчёт stopped (точная позиция) не дольше
DEFAULT_VOLUME = 0.6


class Streams:
    """Потоки на колонках; изменения — события stream {StreamInfo}."""

    def __init__(
        self,
        link: StreamLink,
        devices: Callable[[], list[DeviceInfo]],
        last_active: Callable[[], str | None],
        decode: Decode,
        *,
        events: EventSink,
        clock: Callable[[], float] = time.monotonic,
        start_timeout_s: float = START_TIMEOUT_S,
        stop_wait_s: float = STOP_WAIT_S,
        first_chunk_s: float = FIRST_CHUNK_S,
        probe: Probe | None = None,
    ) -> None:
        """link — колонки; devices() — известные колонки; last_active() — колонка последнего
        разговора; decode(источник, с секунды) — PCM; events — приёмник событий stream;
        probe(источник) — почему его не играть ("" — можно; звук Mac: есть ли устройство ввода)."""
        self._link = link
        self._devices = devices
        self._last_active = last_active
        self._decode = decode
        self._events = events
        self._first_chunk_s = first_chunk_s
        self._probe = probe
        self._queues: dict[str, SpeakerQueue] = {}
        self._volumes: dict[str, float] = {}  # громкость колонки переживает смену очереди
        self._closed = False
        self._runner = Runner(
            link,
            self._queues.get,
            self._publish,
            self._check_device,
            clock=clock,
            start_timeout_s=start_timeout_s,
            stop_wait_s=stop_wait_s,
        )

    def status(self) -> list[StreamInfo]:
        """Колонки, умеющие потоки, и колонки с потоком, по имени."""
        result: list[StreamInfo] = []
        for device in self._devices():
            queue = self._queues.get(device.device_id)
            if self._available(device) or (queue is not None and queue.state != "idle"):
                result.append(self._info(device.device_id))
        return result

    async def play(
        self,
        device_id: str | None,
        items: Sequence[StreamItem],
        *,
        index: int = 0,
        start_s: float = 0.0,
        volume: float | None = None,
    ) -> StreamInfo:
        """Новая очередь на колонке; прежний поток заменяется (см. SpeakerStreams.play)."""
        if self._closed:
            raise StreamRefused("unavailable", texts.STOPPING)
        check_items(items, index)
        target = pick_for_play(device_id, self._devices(), self._link.supports_stream, self._last_active())
        self._check_device(target)
        await self._check_reachable(items)
        level = _clamp(volume) if volume is not None else self._volumes.get(target, DEFAULT_VOLUME)
        async with self._runner.lock(target):
            old = self._queues.get(target)
            if old is not None:
                old.stream = 0  # отчёты прежнего потока — мимо
            queue = SpeakerQueue(target, list(items), level)
            self._queues[target] = queue
            self._volumes[target] = level
            await self._runner.start(queue, index, start_s)
        return self._info(target)

    async def control(self, device_id: str | None, action: StreamAction) -> StreamInfo:
        """Пауза, продолжить, дальше, назад, стоп."""
        queue = self._active_queue(device_id)
        async with self._runner.lock(queue.device_id):
            await self._runner.act(queue, action)
        return self._info(queue.device_id)

    async def set_volume(
        self, device_id: str | None, *, volume: float | None = None, delta: float = 0.0
    ) -> StreamInfo:
        """Громкость музыки колонки: volume (0..1) или сдвиг delta."""
        queue = self._active_queue(device_id)
        async with self._runner.lock(queue.device_id):
            queue.volume = _clamp((queue.volume if volume is None else volume) + delta)
            self._volumes[queue.device_id] = queue.volume
            if queue.state == "playing":
                await self._link.send_stream(queue.device_id, StreamCommand("volume", volume=queue.volume))
            self._publish(queue)
        return self._info(queue.device_id)

    async def open(self, token: str) -> AsyncIterator[bytes] | None:
        """Звук по ссылке колонки (одноразовой); первый кусок уже готов. None — нет ссылки или
        источник не разобрался (колонка сообщит failed, ядро пропустит элемент)."""
        ticket = self._runner.take_ticket(token)
        queue = self._queues.get(ticket.device_id) if ticket is not None else None
        if ticket is None or queue is None or queue.stream != ticket.stream:
            return None
        pcm = self._decode(ticket.source, ticket.start_s, ticket.rate)
        try:
            async with asyncio.timeout(self._first_chunk_s):
                first = await anext(pcm)
        except Exception as error:  # noqa: BLE001 — любой сбой разбора: элемент сломан
            await pcm.aclose()
            _log.warning("Поток %d на %s не открылся: %r", ticket.stream, ticket.device_id, error)
            return None
        except asyncio.CancelledError:
            await pcm.aclose()
            raise
        return _chain(first, pcm)

    def report(self, device_id: str, report: StreamReport | None) -> None:
        """Отчёт stream_status колонки; None — колонка отключилась (поток — на паузу)."""
        queue = self._queues.get(device_id)
        if queue is None:
            return
        if report is None:
            if queue.state == "playing":
                self._runner.paused(queue, texts.GONE)
            return
        if report.stream == 0 or report.stream != queue.stream:
            return  # прежний поток
        queue.reported, queue.played = True, report.played
        if report.state == "playing" and report.played > 0:
            queue.failures = 0
        elif report.state == "stopped" and queue.stopped is not None:
            queue.stopped.set()
        elif report.state in ("ended", "failed"):
            error = (report.error or "download") if report.state == "failed" else ""
            self._runner.spawn(self._runner.after(device_id, report.stream, error))

    async def aclose(self) -> None:
        """Останавливает потоки колонок; новые больше не принимаются. Повторный вызов безопасен."""
        self._closed = True
        playing = [q for q in self._queues.values() if q.state == "playing" and q.stream]
        await asyncio.gather(
            *(self._link.send_stream(q.device_id, StreamCommand("stop", q.stream)) for q in playing),
            return_exceptions=True,
        )
        await self._runner.aclose()

    def _active_queue(self, device_id: str | None) -> SpeakerQueue:
        """Очередь с потоком (играет или на паузе) у названной или выбранной колонки."""
        states: dict[str, StreamPhase] = {d: q.state for d, q in self._queues.items()}
        target = pick_for_control(device_id, states, self._last_active())
        queue = self._queues.get(target)
        if queue is None or queue.state == "idle":
            raise StreamRefused("not_playing", texts.NOT_PLAYING)
        return queue

    async def _check_reachable(self, items: Sequence[StreamItem]) -> None:
        """Источники, которые надо проверить заранее (звук Mac), доступны; иначе StreamRefused."""
        if self._probe is None:
            return
        for source in {item.source for item in items}:
            why = await self._probe(source)
            if why:
                raise StreamRefused("bad_source", why)

    def _check_device(self, device_id: str) -> None:
        """Колонка известна, в сети и умеет потоки; иначе StreamRefused."""
        device = self._device(device_id)
        if device is None:
            raise StreamRefused("unknown_device", texts.UNKNOWN)
        if not device.connected:
            raise StreamRefused("offline", texts.OFFLINE)
        if not self._link.supports_stream(device_id):
            raise StreamRefused("unsupported", texts.UNSUPPORTED)

    def _device(self, device_id: str) -> DeviceInfo | None:
        return next((d for d in self._devices() if d.device_id == device_id), None)

    def _available(self, device: DeviceInfo) -> bool:
        return device.connected and self._link.supports_stream(device.device_id)

    def _info(self, device_id: str) -> StreamInfo:
        device = self._device(device_id)
        name = device.name if device is not None else device_id
        available = device is not None and self._available(device)
        queue = self._queues.get(device_id) or SpeakerQueue(
            device_id, [], self._volumes.get(device_id, DEFAULT_VOLUME)
        )
        return queue.info(name, available)

    def _publish(self, queue: SpeakerQueue) -> None:
        self._events.publish("stream", asdict(self._info(queue.device_id)))


def _clamp(volume: float) -> float:
    """Громкость 0..1 с точностью до тысячных (0.6 + 0.3 — ровно 0.9)."""
    return round(min(max(volume, 0.0), 1.0), 3)


async def _chain(first: bytes, rest: AsyncGenerator[bytes]) -> AsyncGenerator[bytes]:
    """Первый кусок, затем остальное; закрытие закрывает разбор (ffmpeg)."""
    try:
        yield first
        async for chunk in rest:
            yield chunk
    finally:
        await rest.aclose()
