"""Список моделей Ollama: установленные и загруженные в память."""

from typing import Any

import httpx
import ollama

from smartesp.contracts import ExecutorError

LIST_TIMEOUT_S = 5.0  # короткий таймаут: эти вызовы делает интерфейс


def _field(item: Any, name: str) -> Any:
    """Читает поле из объекта ollama или словаря."""
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _items(response: Any) -> list[Any]:
    """Достаёт список моделей из ответа (объект или словарь)."""
    return list(_field(response, "models") or [])


def _name(item: Any) -> str:
    """Имя модели: поле model, а если его нет — name."""
    return str(_field(item, "model") or _field(item, "name") or "")


def _client(client: Any) -> Any:
    """Клиент по умолчанию — локальный ollama.AsyncClient с коротким таймаутом."""
    return client if client is not None else ollama.AsyncClient(timeout=LIST_TIMEOUT_S)


def _wrap(exc: Exception) -> ExecutorError:
    """Превращает ошибку ollama/сети в ExecutorError."""
    return ExecutorError(f"Не удалось получить список моделей Ollama: {exc!r}")


async def list_models(client: Any = None) -> list[tuple[str, int]]:
    """Возвращает установленные модели как пары (имя, размер в байтах).

    Кидает ExecutorError, если Ollama недоступна.
    """
    try:
        response = await _client(client).list()
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
        raise _wrap(exc) from exc
    return [(_name(m), int(_field(m, "size") or 0)) for m in _items(response)]


async def loaded_models(client: Any = None) -> list[str]:
    """Возвращает имена моделей, сейчас загруженных в память (ps).

    Кидает ExecutorError, если Ollama недоступна.
    """
    try:
        response = await _client(client).ps()
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
        raise _wrap(exc) from exc
    return [_name(m) for m in _items(response)]
