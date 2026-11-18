"""Токен доступа: файл в каталоге данных и проверка заголовка."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request


def load_or_create_token(home: Path) -> str:
    """Читает `<home>/token` или создаёт его (права 0600) со случайным токеном.

    Файл всегда появляется сразу с содержимым (временный файл + link/replace),
    поэтому параллельный читатель не увидит пустой файл. Пустой файл заменяется.
    """
    path = home / "token"
    home.mkdir(parents=True, exist_ok=True)
    existing = _read(path)
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    tmp = home / f".token.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(token + "\n")
    try:
        if path.exists():  # пустой или битый файл — заменяем
            os.replace(tmp, path)
            return token
        try:
            os.link(tmp, path)  # атомарно: не затирает файл, созданный параллельно
        except FileExistsError:
            return _read(path) or token
        return token
    finally:
        tmp.unlink(missing_ok=True)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def token_matches(given: str | None, expected: str) -> bool:
    """Сравнивает токены за постоянное время."""
    if not given:
        return False
    return secrets.compare_digest(given.encode(), expected.encode())


def bearer_token(header: str | None) -> str | None:
    """Достаёт значение из `Authorization: Bearer <token>`; иначе None."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value or value != value.strip():
        return None
    return value


def require_token(expected: str):
    """Собирает зависимость FastAPI: неверный токен — 401 без подробностей."""

    def check(request: Request) -> None:
        if not token_matches(bearer_token(request.headers.get("authorization")), expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    return check
