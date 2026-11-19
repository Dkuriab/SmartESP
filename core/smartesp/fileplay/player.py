"""Файл на колонке: загрузка во временный файл, разбор в PCM по ходу и звук ходом ядра (announce)."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

from smartesp.contracts import (
    AskUnavailable,
    AudioUndecodable,
    Delivery,
    DeviceInfo,
    DevicePort,
    EventSink,
    PlaybackRefused,
)

_log = logging.getLogger(__name__)

Decode = Callable[[Path], AsyncGenerator[bytes]]  # файл → PCM s16le 16 кГц моно кусками

UNKNOWN = "Колонка не найдена"
OFFLINE = "Колонка не в сети"
UNSUPPORTED = "Колонка не умеет проигрывать файлы: обновите прошивку (нужен протокол 3)"
PLAYING = "На колонке уже играет файл"
BUSY = "Колонка занята: идёт разговор или объявление"
NO_ANSWER = "Колонка не ответила"
STOPPING = "Ядро останавливается"
STOPPED = "Файл остановлен до начала"
SILENT = "В файле нет звука"
MAX_PLAY_S = 15 * 60 + 30  # потолок хода по стенным часам: 15 мин звука и запас


@dataclass
class _Playback:
    """Файл, отданный колонке: временный файл, поток PCM и отметки хода."""

    device_id: str
    path: Path
    pcm: AsyncGenerator[bytes]
    started: asyncio.Event = field(default_factory=asyncio.Event)  # колонка забрала первый кусок
    entered: bool = False  # задача хода начала работу (отменённая до первого шага — нет)


class FilePlayer:
    """Реализует FilePlayback: на колонке — не больше одного файла; итог — событие playback_finished.

    Файл играет через DevicePort.announce: тот же ход ядра, что у объявлений (колонка сыграет
    «внимание», слово пробуждения прервёт). Загрузка лежит во временном файле, пока он играет.
    """

    def __init__(
        self,
        port: DevicePort,
        devices: Callable[[], list[DeviceInfo]],
        decode: Decode,
        *,
        events: EventSink,
        tmp_dir: Path | None = None,
        max_s: float = MAX_PLAY_S,
    ) -> None:
        """port — колонки; devices() — известные колонки; decode(путь) — разбор файла в PCM по ходу
        (не разобрать — AudioUndecodable, нет программы — AskUnavailable); events — приёмник событий;
        tmp_dir — папка временных файлов (None — системная); max_s — потолок хода по стенным часам."""
        self._port = port
        self._devices = devices
        self._decode = decode
        self._events = events
        self._tmp_dir = tmp_dir
        self._max_s = max_s
        self._busy: set[str] = set()  # колонки с файлом: от начала загрузки до итога
        self._stop_asked: set[str] = set()  # остановить просили, пока файл ещё загружался
        self._tasks: dict[str, asyncio.Task[Delivery]] = {}
        self._closing: set[asyncio.Task[None]] = set()  # закрытие разбора у отменённых до начала
        self._closed = False

    async def play_file(self, device_id: str, source: AsyncIterator[bytes]) -> None:
        """Сохраняет, разбирает и начинает файл; возвращается, когда колонка забрала первый звук.

        Не заиграл — PlaybackRefused (колонки нет, не в сети, протокол < 3, занята, файл не
        разобрать, нет ffmpeg, остановлен до начала, ядро останавливается).
        """
        self._check(device_id)
        self._busy.add(device_id)
        try:
            path, pcm, first = await self._prepare(source)
            if self._closed or device_id in self._stop_asked:
                await pcm.aclose()
                path.unlink(missing_ok=True)
                raise PlaybackRefused(*(("unavailable", STOPPING) if self._closed else ("stopped", STOPPED)))
        except BaseException:
            self._release(device_id)
            raise
        playback = _Playback(device_id, path, pcm)
        audio = _feed(first, pcm, lambda: self._on_start(playback))
        task = asyncio.create_task(self._run(playback, audio), name=f"file-{device_id}")
        task.add_done_callback(lambda _: self._unstarted(playback))
        self._tasks[device_id] = task
        await self._wait_start(task, playback.started)

    async def stop_file(self, device_id: str) -> bool:
        """Отменяет файл колонки (колонке уйдёт cancel_turn); False — файл не играл.

        Файл ещё загружается или разбирается — он не начнётся (его POST получит отказ «stopped»).
        """
        if self._info(device_id) is None:
            raise PlaybackRefused("unknown_device", UNKNOWN)
        task = self._tasks.get(device_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return True
        if device_id in self._busy:
            self._stop_asked.add(device_id)
            return True
        return False

    async def aclose(self) -> None:
        """Останавливает все файлы; новые больше не принимаются. Повторный вызов безопасен."""
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*self._closing, return_exceptions=True)

    def _info(self, device_id: str) -> DeviceInfo | None:
        return next((d for d in self._devices() if d.device_id == device_id), None)

    def _check(self, device_id: str) -> None:
        """Отказ до загрузки: колонки нет, ядро останавливается, не в сети, протокол < 3, уже играет."""
        info = self._info(device_id)
        if info is None:
            raise PlaybackRefused("unknown_device", UNKNOWN)
        if self._closed:
            raise PlaybackRefused("unavailable", STOPPING)
        if not info.connected:
            raise PlaybackRefused("offline", OFFLINE)
        if not self._port.supports_proactive(device_id):
            raise PlaybackRefused("unsupported", UNSUPPORTED)
        if device_id in self._busy:
            raise PlaybackRefused("busy", PLAYING)

    def _release(self, device_id: str) -> None:
        """Колонка снова свободна для файла."""
        self._busy.discard(device_id)
        self._stop_asked.discard(device_id)
        self._tasks.pop(device_id, None)

    async def _prepare(self, source: AsyncIterator[bytes]) -> tuple[Path, AsyncGenerator[bytes], bytes]:
        """Сохраняет загрузку и ждёт первый кусок PCM: так плохой файл отказывает до «внимания»."""
        path = await _save(source, self._tmp_dir)
        pcm = self._decode(path)
        try:
            return path, pcm, await anext(pcm)
        except BaseException as error:
            await pcm.aclose()
            path.unlink(missing_ok=True)
            if isinstance(error, AudioUndecodable):
                raise PlaybackRefused("undecodable", str(error)) from error
            if isinstance(error, AskUnavailable):
                raise PlaybackRefused("unavailable", str(error)) from error
            if isinstance(error, StopAsyncIteration):
                raise PlaybackRefused("undecodable", SILENT) from None
            raise

    async def _wait_start(self, task: asyncio.Task[Delivery], started: asyncio.Event) -> None:
        """Ждёт начала звука; ход кончился раньше — PlaybackRefused по его итогу."""
        waiter = asyncio.ensure_future(started.wait())
        try:
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if started.is_set():
            return
        if task.cancelled():
            raise PlaybackRefused(*(("unavailable", STOPPING) if self._closed else ("stopped", STOPPED)))
        if task.result() == "busy":
            raise PlaybackRefused("busy", BUSY)
        raise PlaybackRefused("offline", NO_ANSWER)

    def _on_start(self, playback: _Playback) -> None:
        playback.started.set()
        self._events.publish("playback_started", {"device_id": playback.device_id})

    async def _run(self, playback: _Playback, audio: AsyncIterator[bytes]) -> Delivery:
        """Ход ядра с файлом (не дольше max_s); итог (отмена — interrupted) публикуется, если звук
        начинался."""
        playback.entered = True
        device_id = playback.device_id
        delivery: Delivery = "lost"
        try:
            async with asyncio.timeout(self._max_s):
                delivery = await self._port.announce(device_id, audio)
        except TimeoutError:
            _log.warning("Файл на %s оборван: играет дольше %.0f с", device_id, self._max_s)
            delivery = "interrupted"
        except asyncio.CancelledError:
            delivery = "interrupted"
            raise
        finally:
            await playback.pcm.aclose()
            playback.path.unlink(missing_ok=True)
            self._release(device_id)
            if playback.started.is_set():
                self._events.publish("playback_finished", {"device_id": device_id, "delivery": delivery})
        return delivery

    def _unstarted(self, playback: _Playback) -> None:
        """Задачу отменили до её первого шага (её finally не выполнялся) — убрать за ней."""
        if playback.entered:
            return
        self._release(playback.device_id)
        playback.path.unlink(missing_ok=True)
        closing = asyncio.get_running_loop().create_task(playback.pcm.aclose())
        self._closing.add(closing)
        closing.add_done_callback(self._closing.discard)


async def _feed(
    first: bytes, rest: AsyncIterator[bytes], on_start: Callable[[], None]
) -> AsyncGenerator[bytes]:
    """Звук для announce: первый кусок (его забор — начало звука), затем остальное."""
    on_start()
    yield first
    async for chunk in rest:
        yield chunk


async def _save(source: AsyncIterator[bytes], directory: Path | None) -> Path:
    """Пишет загрузку во временный файл (запись — в потоке); сбой — файл убирается."""
    handle, name = tempfile.mkstemp(prefix="smartesp-play-", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as file:
            async for chunk in source:
                await asyncio.to_thread(file.write, chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
