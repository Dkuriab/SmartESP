"""Пульт и Ollama: модели в памяти для status, список установленных, выгрузка (внутреннее)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from smartesp.contracts import ExecutorError, ModelNotLoadedError

_log = logging.getLogger(__name__)

OLLAMA_TIMEOUT_S = 2.0  # сколько status ждёт ответа Ollama о загруженных моделях

Loaded = Callable[[], Awaitable[list[str]]]


async def no_unload(name: str) -> None:
    """По умолчанию выгрузки нет."""
    raise ExecutorError("выгрузка моделей не подключена")


async def ollama_state(loaded: Loaded) -> dict[str, object]:
    """{reachable, loaded}: не ответила за OLLAMA_TIMEOUT_S или ошибка — недоступна."""
    try:
        async with asyncio.timeout(OLLAMA_TIMEOUT_S):
            names = await loaded()
    except (ExecutorError, TimeoutError):
        return {"reachable": False, "loaded": []}
    except Exception:  # status не должен падать из-за Ollama
        _log.warning("Ollama: список загруженных моделей не получен", exc_info=True)
        return {"reachable": False, "loaded": []}
    return {"reachable": True, "loaded": names}


async def model_list(
    models: Callable[[], Awaitable[list[tuple[str, int]]]], supports_tools: Callable[[str], Awaitable[bool]]
) -> list[dict[str, Any]]:
    """Установленные модели в форме API: [{name, size_bytes, supports_tools}]."""
    listed = await models()
    tools = await asyncio.gather(*(supports_tools(name) for name, _ in listed))
    return [
        {"name": name, "size_bytes": size, "supports_tools": ok}
        for (name, size), ok in zip(listed, tools, strict=True)
    ]


async def unload_loaded(loaded: Loaded, unload: Callable[[str], Awaitable[None]], name: str) -> None:
    """Выгружает модель, только если она сейчас в памяти: иначе запрос выгрузки загрузил бы её.

    Нет в памяти — ModelNotLoadedError; Ollama недоступна — ExecutorError.
    """
    if name not in await loaded():
        raise ModelNotLoadedError(name)
    _log.info("Выгружаю модель %s из памяти Ollama по просьбе интерфейса", name)
    await unload(name)
