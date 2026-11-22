"""Скачивание модели отпечатков в фоне: одна задача, ход скачивания и ошибка для интерфейса."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from smartesp.contracts import SpeakerModelState

from .model import MODEL_ID, MODEL_SIZE_MB, MODEL_TITLE, Progress

_log = logging.getLogger(__name__)

type Fetch = Callable[[Progress], object]  # качает модель (синхронно, в потоке); сбой — исключение


class ModelFetcher:
    """Фоновое скачивание модели: start() запускает (если файла нет и не качается), state() — ход."""

    def __init__(self, path: Path, fetch: Fetch, on_ready: Callable[[], None] | None = None) -> None:
        """path — файл модели (есть — модель готова); fetch(progress) — скачать; on_ready — после."""
        self._path = path
        self._fetch = fetch
        self._on_ready = on_ready
        self._task: asyncio.Task[None] | None = None
        self._done, self._total = 0, None
        self._error = ""

    def ready(self) -> bool:
        """Скачана ли модель."""
        return self._path.is_file()

    def state(self) -> SpeakerModelState:
        """Состояние для интерфейса."""
        downloading = self._task is not None and not self._task.done()
        return SpeakerModelState(
            MODEL_ID,
            MODEL_TITLE,
            MODEL_SIZE_MB,
            self.ready(),
            downloading,
            self._done,
            self._total,
            self._error,
        )

    def start(self) -> SpeakerModelState:
        """Запускает скачивание в фоне; готово или уже качается — ничего не делает."""
        if not self.ready() and (self._task is None or self._task.done()):
            self._done, self._total, self._error = 0, None, ""
            self._task = asyncio.create_task(self._run(), name="speaker-model-download")
        return self.state()

    def _progress(self, done: int, total: int | None) -> None:
        self._done, self._total = done, total  # из потока: простые присваивания

    async def _run(self) -> None:
        try:
            await asyncio.to_thread(self._fetch, self._progress)
        except Exception as error:  # noqa: BLE001 — ошибка уходит в состояние для интерфейса
            _log.warning("Модель узнавания голоса не скачана: %s", error)
            self._error = str(error) or type(error).__name__
            return
        if self._on_ready is not None:
            self._on_ready()

    async def aclose(self) -> None:
        """Перестаёт ждать скачивание (поток докачает сам; процесс его не ждёт)."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
