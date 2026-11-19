"""Модели Ollama: установленные, загруженные в память, выгрузка из памяти."""

from collections.abc import Awaitable, Callable
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


def _wrap(exc: Exception, what: str) -> ExecutorError:
    """Превращает ошибку ollama/сети в ExecutorError."""
    return ExecutorError(f"Не удалось {what}: {exc!r}")


async def _call(client: Any, method: str, what: str = "получить список моделей Ollama", **kwargs: Any) -> Any:
    """Вызывает метод клиента; свой клиент (если не передан) закрывает после вызова.

    Переданный снаружи клиент не закрывается.
    """
    own = client is None
    c: Any = ollama.AsyncClient(timeout=LIST_TIMEOUT_S) if own else client
    try:
        call: Callable[..., Awaitable[Any]] = getattr(c, method)
        return await call(**kwargs)
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
        raise _wrap(exc, what) from exc
    finally:
        if own:
            await c.close()


async def list_models(client: Any = None) -> list[tuple[str, int]]:
    """Возвращает установленные модели как пары (имя, размер в байтах).

    Кидает ExecutorError, если Ollama недоступна.
    """
    response = await _call(client, "list")
    return [(_name(m), int(_field(m, "size") or 0)) for m in _items(response)]


async def loaded_models(client: Any = None) -> list[str]:
    """Возвращает имена моделей, сейчас загруженных в память (ps).

    Кидает ExecutorError, если Ollama недоступна.
    """
    response = await _call(client, "ps")
    return [_name(m) for m in _items(response)]


async def unload_model(name: str, client: Any = None) -> None:
    """Выгружает модель из памяти (keep_alive=0); не загруженную такой запрос сначала загрузит.

    Кидает ExecutorError, если Ollama недоступна или ответила ошибкой.
    """
    await _call(client, "generate", f"выгрузить модель {name}", model=name, prompt="", keep_alive=0)


async def model_capabilities(model: str, client: Any = None) -> frozenset[str]:
    """Возвращает возможности модели (show): например completion, tools.

    Ошибка или отсутствие модели — пустое множество, без исключения.
    """
    own = client is None
    c: Any = ollama.AsyncClient(timeout=LIST_TIMEOUT_S) if own else client
    try:
        response = await c.show(model)
        return frozenset(str(x) for x in _field(response, "capabilities") or [])
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        return frozenset()
    finally:
        if own:
            await c.close()
