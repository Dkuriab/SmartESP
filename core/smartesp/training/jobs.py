"""Шаг обучения — подпроцесс набора: ход строками JSON из stdout, журнал из stderr, остановка.

Протокол набора (см. trainers/wakeword/wakeword_trainer/progress.py): {"stage", "done", "total"} — ход,
{"log": …} — строка журнала, {"result": {…}} — итог, {"error": …} — понятная ошибка.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from smartesp.contracts import JobStatus, TrainJob

_log = logging.getLogger(__name__)
LOG_LINES = 300  # столько последних строк журнала держим
STOP_GRACE_S = 10.0  # после SIGTERM ждём столько, потом SIGKILL
_LINE_LIMIT = 1 << 22  # строки с «\r»-ходом microWakeWord бывают длинными


@dataclass
class StepJob:
    """Идущий шаг: argv и окружение подпроцесса, текущее состояние."""

    state: TrainJob
    argv: list[str]
    env: dict[str, str]
    log: deque[str] = field(default_factory=lambda: deque[str](maxlen=LOG_LINES))
    proc: asyncio.subprocess.Process | None = None
    stopping: bool = False

    def snapshot(self) -> TrainJob:
        """Состояние с последними строками журнала."""
        return replace(self.state, log=tuple(self.log))

    def take_stdout(self, line: str) -> None:
        """Строка JSON набора → ход, журнал, итог или ошибка; не JSON — в журнал."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            self.take_log(line)
            return
        if not isinstance(data, dict):
            return
        if "stage" in data:
            self.state = replace(
                self.state,
                stage=str(data["stage"]),
                done=int(data.get("done", 0)),
                total=int(data.get("total", 0)),
            )
        if "log" in data:
            self.take_log(str(data["log"]))
        if "error" in data:
            self.state = replace(self.state, error=str(data["error"]))
            self.take_log(f"Ошибка: {data['error']}")
        if isinstance(data.get("result"), dict):
            self.state = replace(self.state, result=data["result"])

    def take_log(self, text: str) -> None:
        """Строка журнала; «\\r»-ход оставляет последнее значение."""
        line = text.rstrip("\n").split("\r")[-1].rstrip()
        if line:
            self.log.append(line)

    async def run(self) -> None:
        """Запускает подпроцесс и читает его до конца; итог — в state.status."""
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                limit=_LINE_LIMIT,
                start_new_session=True,  # своя группа: «Стоп» гасит и вложенные uv/python
            )
        except OSError as error:
            self._finish("failed", f"не удалось запустить: {error}")
            return
        assert self.proc.stdout is not None and self.proc.stderr is not None
        await asyncio.gather(
            self._read(self.proc.stdout, self.take_stdout), self._read(self.proc.stderr, self.take_log)
        )
        code = await self.proc.wait()
        if self.stopping:
            self._finish("cancelled", "")
        elif code == 0:
            self._finish("done", "")
        else:
            self._finish("failed", self.state.error or f"шаг завершился с кодом {code} — см. журнал")

    @staticmethod
    async def _read(stream: asyncio.StreamReader, take: Callable[[str], None]) -> None:
        while line := await stream.readline():
            take(line.decode("utf-8", errors="replace"))

    def _finish(self, status: JobStatus, error: str) -> None:
        self.state = replace(self.state, status=status, error=error, finished_at=time.time())
        _log.info("Обучение %s: шаг %s — %s %s", self.state.kit, self.state.step, status, error)

    async def stop(self) -> None:
        """SIGTERM группе процесса, через STOP_GRACE_S — SIGKILL."""
        if self.proc is None or self.proc.returncode is not None:
            return
        self.stopping = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(self.proc.wait(), STOP_GRACE_S)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGKILL)
