"""Клиент ядра (бот Telegram и т. п.): обычный подпроцесс, не MCP. Хаб его запускает и держит.

Клиент получает адрес и токен API ядра в окружении (SMARTESP_URL, SMARTESP_TOKEN) и ходит в API
сам. Ядро копит последние строки его журнала (stdout и stderr) и понимает в stdout строки JSON
`{"suggest": {"key", "value", "text"}}` — предложение дописать значение в объявленную настройку-список
(«Написал незнакомый: Аня (id 123)» → «Добавить»). Упавший клиент перезапускается, как коннектор.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from mcp import types

from smartesp.contracts import Suggestion, ToolResult

from .connector import DATA_ENV, STABLE_S, STOP_TIMEOUT_S
from .messages import logger
from .specs import ConnectorSpec, StateName

LOG_LINES = 200
MAX_SUGGESTIONS = 10
_DROPPED_ENV = ("VIRTUAL_ENV",)


class ClientProcess:
    """Запускает клиента и перезапускает после падения; тот же облик, что у Connector для хаба."""

    def __init__(
        self,
        spec: ConnectorSpec,
        data_dir: Path,
        core_env: Mapping[str, str],
        *,
        on_change: Callable[[], None],
        restart_delays_s: tuple[float, ...],
    ) -> None:
        self.spec = spec
        self.state: StateName = "starting" if spec.enabled else "disabled"
        self.error = ""
        self.tools: tuple[types.Tool, ...] = ()  # инструментов у клиента нет
        self.log: deque[str] = deque(maxlen=LOG_LINES)
        self.suggestions: dict[str, Suggestion] = {}  # по значению: одно предложение на человека
        self._data_dir = data_dir / "connectors" / spec.id
        self._core_env = dict(core_env)
        self._on_change = on_change
        self._delays = restart_delays_s or (1.0,)
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._settled = asyncio.Event()
        self._stopping = False

    def launch(self) -> None:
        """Запускает клиента в фоне (выключенного — нет)."""
        if not self.spec.enabled:
            self._settled.set()
            return
        self._task = asyncio.create_task(self._supervise(), name=f"client-{self.spec.id}")

    async def wait_settled(self) -> None:
        """Ждёт первой попытки запуска."""
        await self._settled.wait()

    async def call(
        self, tool: str, arguments: dict[str, object], person: str | None, timeout: float
    ) -> ToolResult:
        """У клиента нет инструментов."""
        return ToolResult(f"У «{self.spec.name}» нет инструментов.", is_error=True)

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _DROPPED_ENV}
        return {
            **env,
            **self.spec.env,
            **self._core_env,
            DATA_ENV: str(self._data_dir),
            "PYTHONUNBUFFERED": "1",
        }

    async def _supervise(self) -> None:
        """Запуски до остановки; между падениями — задержки restart_delays_s."""
        failures = 0
        while not self._stopping:
            began = time.monotonic()
            error = await self._run_once()
            if self._stopping:
                return
            self._set("failed", error)
            if time.monotonic() - began >= STABLE_S:
                failures = 0
            delay = self._delays[min(failures, len(self._delays) - 1)]
            failures += 1
            logger.warning("Клиент %s упал (%s); перезапуск через %g с", self.spec.id, error, delay)
            await asyncio.sleep(delay)

    async def _run_once(self) -> str:
        """Одна жизнь процесса; возвращает текст ошибки."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.spec.command,
                *self.spec.args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
                start_new_session=True,
            )
        except OSError as error:
            self._settled.set()
            return f"Не удалось запустить: {error.strerror or error}."
        self._set("ready", "")
        assert self._proc.stdout is not None and self._proc.stderr is not None
        await asyncio.gather(self._read(self._proc.stdout, True), self._read(self._proc.stderr, False))
        code = await self._proc.wait()
        last = self.log[-1] if self.log else ""
        return f"Завершился с кодом {code}" + (f": {last}" if last else "")

    async def _read(self, stream: asyncio.StreamReader, structured: bool) -> None:
        while raw := await stream.readline():
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line and not (structured and self._take(line)):
                self.log.append(line)
                self._on_change()

    def _take(self, line: str) -> bool:
        """Строка JSON с предложением → в suggestions; True — строка понята."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return False
        item: object = cast(dict[str, object], data).get("suggest") if isinstance(data, dict) else None
        if not isinstance(item, dict):
            return False
        fields = cast(dict[str, object], item)
        key, value, text = (str(fields.get(k) or "") for k in ("key", "value", "text"))
        if key and value and (value in self.suggestions or len(self.suggestions) < MAX_SUGGESTIONS):
            self.suggestions[value] = Suggestion(key, value, text or value)
            self._on_change()
        return True

    def _set(self, state: StateName, error: str) -> None:
        self.state, self.error = state, error
        self._settled.set()
        self._on_change()

    async def stop(self, timeout_s: float = STOP_TIMEOUT_S) -> None:
        """SIGTERM группе процесса, не закрылся за timeout_s — SIGKILL; не бросает исключений."""
        self._stopping = True
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout_s)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
