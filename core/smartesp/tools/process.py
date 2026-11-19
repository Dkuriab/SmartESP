"""Процесс коннектора: команда запуска с записью номера процесса и жёсткое завершение."""

from __future__ import annotations

import os
import shutil
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path

from mcp import StdioServerParameters

from .messages import logger

SHELL = "/bin/sh"
# sh пишет свой номер в файл и exec'ом становится коннектором: номер тот же, а группа процессов —
# своя (SDK запускает коннектор в новой сессии), так что её можно убить целиком
_RECORD_PID = 'echo $$ > "$0" && exec "$@"'
_DROPPED_ENV = ("VIRTUAL_ENV",)  # окружение ядра: uv коннектора ругался бы на чужое окружение


def launch_params(
    command: str, args: Sequence[str], env: Mapping[str, str], pid_file: Path
) -> StdioServerParameters:
    """Параметры запуска через sh: номер процесса — в pid_file.

    Команды нет в PATH из env — FileNotFoundError (как при запуске без обёртки).
    """
    if shutil.which(command, path=env.get("PATH")) is None:
        raise FileNotFoundError(command)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.unlink(missing_ok=True)
    clean = {k: v for k, v in env.items() if k not in _DROPPED_ENV}
    return StdioServerParameters(
        command=SHELL, args=["-c", _RECORD_PID, str(pid_file), command, *args], env=clean
    )


def kill_group(pid_file: Path, connector_id: str) -> None:
    """SIGKILL группе процессов коннектора по номеру из pid_file; нет файла или группы — ничего."""
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    logger.warning("Коннектор %s не закрылся вовремя: процесс %d убит", connector_id, pid)
