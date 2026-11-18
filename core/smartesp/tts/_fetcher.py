"""Общие скачивания голосов: одно на файл (папку) голоса, сколько бы голосов его ни ждали."""

import asyncio
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ._progress import ProgressRelay
from .catalog import voice_path

Publish = Callable[[str, dict[str, object]], None]


class Download(Protocol):
    """Синхронное скачивание голоса (как download_voice); вызывается в потоке."""

    def __call__(
        self, kind: str, voice: str, home: Path, *, progress: Callable[[int, int | None], None] | None = ...
    ) -> None: ...


@dataclass
class _Shared:
    task: asyncio.Task[None]
    waiters: int = 0


class SharedFetcher:
    """Качает голоса в потоке, по одному скачиванию на цель — путь voice_path().

    Голоса Silero (и Vosk) лежат в одном файле (папке), поэтому их скачивания —
    одно и то же: ждущие одной цели делят его. Скачивание обрывается, когда уходит
    последний ждущий. Новое скачивание той же цели ждёт, пока поток прежнего
    закончит (оборвётся на ближайшем куске), чтобы не писать в один .part вдвоём.

    События voice_download идут один раз на цель, с видом и голосом того запроса,
    который начал скачивание.
    """

    def __init__(self, home: Path, download: Download, publish: Publish) -> None:
        self._home = home
        self._download = download
        self._publish = publish
        self._fetches: dict[Path, _Shared] = {}
        self._threads: dict[Path, asyncio.Future[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def fetch(self, kind: str, voice: str) -> None:
        """Скачивает голос (или ждёт уже идущее скачивание его цели).

        Ошибка скачивания пробрасывается; неизвестный голос — ValueError.
        """
        target = voice_path(kind, voice, self._home)
        shared = self._fetches.get(target)
        if shared is None:
            shared = _Shared(asyncio.create_task(self._run(kind, voice, target)))
            self._fetches[target] = shared
            self._tasks.add(shared.task)
            shared.task.add_done_callback(functools.partial(self._finished, target, shared))
        shared.waiters += 1
        try:
            await asyncio.shield(shared.task)
        finally:
            shared.waiters -= 1
            if shared.waiters == 0 and not shared.task.done():
                self._forget(target, shared)
                shared.task.cancel()

    async def aclose(self) -> None:
        """Обрывает все скачивания и дожидается их задач (не потоков)."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    def _finished(self, target: Path, shared: _Shared, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._forget(target, shared)
        if not task.cancelled():
            task.exception()  # ошибку уже получили ждущие; не даём asyncio ругаться

    def _forget(self, target: Path, shared: _Shared) -> None:
        if self._fetches.get(target) is shared:
            del self._fetches[target]

    async def _run(self, kind: str, voice: str, target: Path) -> None:
        previous = self._threads.get(target)
        if previous is not None:
            await asyncio.wait([previous])  # прежний поток ещё может писать .part

        def emit(done: int, total: int | None) -> None:
            self._publish("voice_download", {"kind": kind, "voice": voice, "done": done, "total": total})

        loop = asyncio.get_running_loop()
        relay = ProgressRelay(loop, emit)
        emit(0, None)
        call = functools.partial(self._download, kind, voice, self._home, progress=relay)
        thread = loop.run_in_executor(None, call)
        self._threads[target] = thread
        thread.add_done_callback(functools.partial(self._thread_done, target))
        try:
            await asyncio.shield(thread)  # отмена не теряет поток: его ждёт следующее скачивание
        finally:
            relay.stop()

    def _thread_done(self, target: Path, thread: asyncio.Future[None]) -> None:
        if self._threads.get(target) is thread:
            del self._threads[target]
        if not thread.cancelled():
            thread.exception()  # брошенный поток кончается DownloadAbandoned — это норма
