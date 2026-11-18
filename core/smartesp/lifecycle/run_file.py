"""Файл запуска <data>/run/core.json: по нему приложение узнаёт порт и pid ядра."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

_log = logging.getLogger(__name__)


class RunFile:
    """Пишет файл запуска после подъёма сервера и удаляет при остановке."""

    def __init__(self, path: Path) -> None:
        """path — обычно <data>/run/core.json."""
        self._path = path

    def write(self, port: int) -> None:
        """Пишет {"port", "pid", "started_at"} атомарно: читатель не увидит половину файла."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"port": port, "pid": os.getpid(), "started_at": time.time()}
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self._path)
        _log.info("Файл запуска: %s (порт %d, pid %d)", self._path, port, data["pid"])

    def remove(self) -> None:
        """Удаляет файл, если его написал этот процесс; файл другого ядра не трогает."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict) and data.get("pid") == os.getpid():  # pyright: ignore[reportUnknownMemberType]
            self._path.unlink(missing_ok=True)
