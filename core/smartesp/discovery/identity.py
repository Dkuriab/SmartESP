"""Постоянный id ядра: колонка запоминает его и при нескольких ядрах выбирает «своё»."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ID_FILE = "core_id"
ID_BYTES = 6  # 12 hex-знаков


def load_or_create_core_id(home: Path) -> str:
    """Читает `<home>/core_id` или создаёт его один раз (12 hex-знаков); битый файл заменяется.

    Запись атомарная (временный файл + replace): читатель не увидит половину id.
    """
    path = home / ID_FILE
    existing = _read(path)
    if existing:
        return existing
    core_id = secrets.token_hex(ID_BYTES)
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / f".{ID_FILE}.{os.getpid()}"
    tmp.write_text(core_id + "\n", encoding="utf-8")
    tmp.replace(path)
    return core_id


def _read(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    valid = len(text) == ID_BYTES * 2 and all(c in "0123456789abcdef" for c in text)
    return text if valid else ""
