"""Токен доступа: файл в каталоге данных и проверка заголовка."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request


def load_or_create_token(home: Path) -> str:
    """Читает `<home>/token` или создаёт его (права 0600) со случайным токеном."""
    path = home / "token"
    home.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(token + "\n")
    return token


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
    value = value.strip()
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def require_token(expected: str):
    """Собирает зависимость FastAPI: неверный токен — 401 без подробностей."""

    def check(request: Request) -> None:
        if not token_matches(bearer_token(request.headers.get("authorization")), expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    return check
