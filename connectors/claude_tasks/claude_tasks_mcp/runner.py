"""Запуск Claude Code в режиме «один запрос — один ответ» (`claude -p`).

Права: правки только без вопросов (`--permission-mode acceptEdits`), набор встроенных
инструментов ограничен (`--tools`) и разрешён без вопросов (`--allowedTools`), MCP-серверы
из чужих настроек не подключаются (`--strict-mcp-config`). Флаг обхода всех проверок
не используется никогда. Задача идёт через stdin — так текст не спутать с флагами.
"""

import asyncio
import contextlib
import json
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

STOP_GRACE_S = 5.0

_SUBTYPES = {
    "error_max_turns": "закончились шаги",
    "error_during_execution": "ошибка во время работы",
}


@dataclass(frozen=True)
class RunResult:
    """Итог запуска: `ok` — ответ Claude в `text`; иначе в `text` — причина для речи."""

    ok: bool
    text: str


class Runner(Protocol):
    """Выполняет задачу `prompt` в папке `folder` и возвращает итог (отмена — CancelledError)."""

    async def __call__(self, prompt: str, folder: Path) -> RunResult: ...


def find_claude(configured: str) -> str | None:
    """Путь к `claude`: из настройки, иначе из PATH, иначе стандартный `~/.local/bin/claude`."""
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home() / ".local" / "bin" / "claude"
    return str(home) if os.access(home, os.X_OK) else None


def build_args(binary: str, tools: tuple[str, ...]) -> list[str]:
    """Аргументы запуска: печать ответа JSON, правки без вопросов, только `tools`."""
    listed = ",".join(tools)
    return [
        binary,
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        f"--tools={listed}",
        f"--allowedTools={listed}",
        "--strict-mcp-config",
    ]


def _first_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def _from_json(data: dict[str, Any], code: int | None) -> RunResult:
    text = data.get("result")
    text = text.strip() if isinstance(text, str) else ""
    subtype = str(data.get("subtype", ""))
    if data.get("is_error") or subtype.startswith("error"):
        reason = _first_line(text) or _SUBTYPES.get(subtype) or f"программа claude завершилась с кодом {code}"
        return RunResult(False, reason)
    return RunResult(True, text)


def parse_output(stdout: bytes, code: int | None, stderr: bytes) -> RunResult:
    """Разбирает вывод `claude -p --output-format json` и код выхода."""
    out = stdout.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return _from_json(dict[str, Any](data), code)  # pyright: ignore[reportUnknownArgumentType]
    if code == 0 and out:
        return RunResult(True, out)
    err = [line.strip() for line in stderr.decode("utf-8", errors="replace").splitlines() if line.strip()]
    return RunResult(False, err[-1][:200] if err else f"программа claude завершилась с кодом {code}")


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """Останавливает группу процессов Claude: TERM, через несколько секунд — KILL."""
    for sig, wait_s in ((signal.SIGTERM, STOP_GRACE_S), (signal.SIGKILL, None)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)
        try:
            await asyncio.wait_for(proc.wait(), wait_s)
            return
        except TimeoutError:
            continue


class ClaudeRunner:
    """Настоящий запуск `claude` подпроцессом asyncio в папке задачи."""

    def __init__(self, claude_bin: str, tools: tuple[str, ...]) -> None:
        self._claude_bin = claude_bin
        self._tools = tools

    async def __call__(self, prompt: str, folder: Path) -> RunResult:
        """Запускает задачу и ждёт ответа; при отмене останавливает процесс и пробрасывает отмену."""
        binary = find_claude(self._claude_bin)
        if binary is None:
            return RunResult(False, "не найдена программа claude")
        try:
            proc = await asyncio.create_subprocess_exec(
                *build_args(binary, self._tools),
                cwd=folder,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return RunResult(False, f"не удалось запустить claude: {exc.strerror or exc}")
        try:
            stdout, stderr = await proc.communicate(prompt.encode("utf-8"))
        except BaseException:
            await asyncio.shield(_stop(proc))
            raise
        return parse_output(stdout, proc.returncode, stderr)
