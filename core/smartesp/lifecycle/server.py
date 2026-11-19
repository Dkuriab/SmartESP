"""Сервер uvicorn с честной остановкой вместо мгновенной."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from types import FrameType

import uvicorn

_log = logging.getLogger(__name__)

STOP_LIMIT_S = 12.0  # с выходом процесса — меньше 15 с, после которых приложение убивает ядро


class GracefulServer(uvicorn.Server):
    """uvicorn.Server, который по первой просьбе об остановке сначала выполняет stop().

    exit_requested — остановку просили сигналом или request_stop() (а не только
    stop_after): тогда перезапуск отменяется, процесс просто выходит.
    Сигналы SIGINT/SIGTERM, request_stop() и stop_after() ведут к одной остановке:
    первая просьба запускает stop() (не дольше limit_s секунд), после неё сервер
    выходит. Просьбы во время остановки её не прерывают, а только уточняют итог
    (exit_requested). Единственный аварийный выход — вторая просьба о выходе
    (повторный Ctrl+C/SIGTERM, сигнал после закрытого stdin): немедленный выход
    (force_exit). Сигнал после остановки не поднимается снова, поэтому процесс
    завершается с кодом 0.
    Создавать внутри работающего цикла asyncio.
    """

    def __init__(
        self,
        config: uvicorn.Config,
        stop: Callable[[], Awaitable[None]],
        *,
        on_started: Callable[[int], None] | None = None,
        limit_s: float = STOP_LIMIT_S,
    ) -> None:
        """stop — честная остановка частей; on_started(порт) — сервер уже принимает соединения."""
        super().__init__(config)
        self._stop = stop
        self._on_started = on_started
        self._limit_s = limit_s
        self._loop = asyncio.get_running_loop()
        self._stopping: asyncio.Task[None] | None = None
        self._watchers: set[asyncio.Task[None]] = set()
        self._exit_requests = 0  # просьбы о выходе, дошедшие до цикла
        self.exit_requested = False

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        """Работает до конца остановки; ждущие stop_after снимаются."""
        try:
            await super().serve(sockets)
        finally:
            for task in list(self._watchers):
                task.cancel()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Поднимает сервер и сообщает фактический порт в on_started."""
        await super().startup(sockets)
        if self.started and self._on_started is not None:
            self._on_started(self._port())

    def request_stop(self) -> None:
        """Просит остановку и выход (без перезапуска); можно звать из любого потока.

        После закрытия цикла ничего не делает.
        """
        self.exit_requested = True
        try:
            self._loop.call_soon_threadsafe(self._on_exit_request)
        except RuntimeError:  # цикл уже закрыт: процесс и так выходит
            pass

    def stop_after(self, waiting: Awaitable[object]) -> None:
        """Просит остановку, когда waiting завершится (например, просьба о перезапуске).

        Во время уже идущей остановки ничего не делает: её не прерывает.
        """

        async def watch() -> None:
            await waiting
            self._start_stop()

        task = self._loop.create_task(watch())
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        """Сигнал — та же просьба об остановке (в _captured_signals не попадает)."""
        self.request_stop()

    def _on_exit_request(self) -> None:
        self._exit_requests += 1
        if self._exit_requests > 1 and self._stopping is not None:
            _log.warning("Повторная просьба о выходе — выхожу сразу")
            self.force_exit = True
            self.should_exit = True
            return
        self._start_stop()

    def _start_stop(self) -> None:
        """Первая просьба запускает честную остановку; следующие её не трогают."""
        if self._stopping is None:
            self._stopping = self._loop.create_task(self._graceful(), name="graceful-stop")

    async def _graceful(self) -> None:
        try:
            async with asyncio.timeout(self._limit_s):
                await self._stop()
        except TimeoutError:
            _log.error("Остановка не уложилась в %g с — выхожу как есть", self._limit_s)
        except Exception:
            _log.error("Сбой при остановке — выхожу как есть", exc_info=True)
        finally:
            self.should_exit = True

    def _port(self) -> int:
        for server in self.servers:
            for sock in server.sockets:
                name = sock.getsockname()
                if isinstance(name, tuple):
                    return int(name[1])  # pyright: ignore[reportUnknownArgumentType]
        return self.config.port
