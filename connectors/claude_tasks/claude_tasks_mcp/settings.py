"""Настройки коннектора из переменных окружения.

- `CLAUDE_TASK_FOLDERS` — разрешённые папки: `имя=путь;имя=путь` (первая — по умолчанию);
- `CLAUDE_TASK_TOOLS` — инструменты Claude Code через запятую (по умолчанию без Bash и сети);
- `CLAUDE_TASK_TIMEOUT_MIN` — предел времени задачи в минутах (по умолчанию 30);
- `CLAUDE_BIN` — путь к программе `claude` (по умолчанию ищется в PATH).
"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
DEFAULT_TIMEOUT_S = 30 * 60.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    """Настройки: папки (имя → настоящий путь, по порядку), инструменты, предел, программа."""

    folders: tuple[tuple[str, Path], ...]
    tools: tuple[str, ...]
    timeout_s: float
    claude_bin: str


def _parse_folders(raw: str) -> tuple[tuple[str, Path], ...]:
    """`имя=путь;…` → пары с путями через realpath; неверные и повторные имена пропускаются."""
    folders: list[tuple[str, Path]] = []
    for item in raw.split(";"):
        if not item.strip():
            continue
        name, sep, path = item.partition("=")
        name, path = name.strip(), path.strip()
        if not sep or not name or not path:
            logger.warning("CLAUDE_TASK_FOLDERS: пропускаю запись без «имя=путь»: %r", item)
            continue
        if any(known.casefold() == name.casefold() for known, _ in folders):
            logger.warning("CLAUDE_TASK_FOLDERS: имя %r повторяется, беру первое", name)
            continue
        folders.append((name, Path(os.path.realpath(os.path.expanduser(path)))))
    return tuple(folders)


def _parse_tools(raw: str) -> tuple[str, ...]:
    """Инструменты через запятую или пробел; пусто — по умолчанию."""
    tools = tuple(t for t in raw.replace(",", " ").split() if t)
    return tools or DEFAULT_TOOLS


def _parse_timeout(raw: str) -> float:
    """Минуты (можно с запятой) → секунды; пусто или неверно — по умолчанию."""
    if not raw.strip():
        return DEFAULT_TIMEOUT_S
    try:
        minutes = float(raw.strip().replace(",", "."))
    except ValueError:
        minutes = 0.0
    if minutes <= 0:
        logger.warning("CLAUDE_TASK_TIMEOUT_MIN: неверное значение %r, беру 30 минут", raw)
        return DEFAULT_TIMEOUT_S
    return minutes * 60


def load_settings(env: Mapping[str, str]) -> Settings:
    """Читает настройки из окружения `env`."""
    return Settings(
        folders=_parse_folders(env.get("CLAUDE_TASK_FOLDERS", "")),
        tools=_parse_tools(env.get("CLAUDE_TASK_TOOLS", "")),
        timeout_s=_parse_timeout(env.get("CLAUDE_TASK_TIMEOUT_MIN", "")),
        claude_bin=env.get("CLAUDE_BIN", "").strip(),
    )
