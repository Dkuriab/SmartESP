"""Имена инструментов для модели: допустимые символы, длина, уникальность."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Container

from smartesp.contracts import DELEGATE_TOOL

MAX_NAME = 64  # предел длины имени инструмента у API моделей
RESERVED = frozenset({DELEGATE_TOOL})  # имена ядра: коннектор их не получает
_BAD_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_HASH_LEN = 8


def safe_name(name: str, *, hashed: bool = False) -> str:
    """Имя только из [a-zA-Z0-9_-] не длиннее MAX_NAME.

    Длинное (или hashed=True) обрезается, и к нему добавляется короткий хеш
    исходного имени — так разные длинные имена не сливаются.
    """
    clean = _BAD_CHARS.sub("_", name) or "tool"
    if len(clean) <= MAX_NAME and not hashed:
        return clean
    digest = hashlib.sha1(name.encode()).hexdigest()[:_HASH_LEN]
    return f"{clean[: MAX_NAME - _HASH_LEN - 1]}_{digest}"


def pick_name(taken: Container[str], connector_id: str, tool: str) -> str | None:
    """Свободное имя для инструмента tool коннектора connector_id.

    Пробует по очереди: своё имя, `<id>_<имя>`, `<id>_<имя>` с хешем; все
    очищены safe_name. Занятые (taken) и зарезервированные (RESERVED) пропускает.
    Возвращает None, если свободного нет.
    """
    prefixed = f"{connector_id}_{tool}"
    for candidate in (safe_name(tool), safe_name(prefixed), safe_name(prefixed, hashed=True)):
        if candidate not in taken and candidate not in RESERVED:
            return candidate
    return None
