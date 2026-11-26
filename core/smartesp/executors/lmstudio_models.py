"""Модели LM Studio: список для выбора в интерфейсе и возможности для сети исполнителей.

Список — из REST API LM Studio: /api/v1/models (новые версии), /api/v0/models (прежние), запасной
путь — OpenAI-совместимый /v1/models (там нет ни загруженности, ни умения инструментов).
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from smartesp.contracts import LMSTUDIO_MODEL_PREFIX, ExecutorError

from .lmstudio_executor import connect_error, server_url

LIST_TIMEOUT_S = 5.0  # короткий: список запрашивает интерфейс
MODEL_PATHS = ("/api/v1/models", "/api/v0/models", "/v1/models")
_SKIPPED_TYPES = ("embedding", "embeddings")  # модели для поиска по смыслу — не для разговора
# модель LM Studio в сети: инструменты есть у любой (без родной поддержки — общий формат LM Studio)
LMSTUDIO_CAPABILITIES = frozenset({"completion", "tools"})


def _loaded(item: dict[str, Any]) -> bool | None:
    """Загружена ли модель: loaded_instances (v1) или state (v0); не сказано — None."""
    if isinstance(item.get("loaded_instances"), list):
        return bool(item["loaded_instances"])
    state = item.get("state")
    return state == "loaded" if isinstance(state, str) else None


def _tools(item: dict[str, Any]) -> bool | None:
    """Родное умение инструментов: capabilities.trained_for_tool_use (v1) или «tool_use» в списке (v0)."""
    caps = item.get("capabilities")
    if isinstance(caps, dict):
        value = cast(dict[str, object], caps).get("trained_for_tool_use")
        return value if isinstance(value, bool) else None
    if isinstance(caps, list):
        return "tool_use" in caps
    return None


def model_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Модель из ответа LM Studio: {id, name, loaded, tools} (неизвестное — None)."""
    model_id = str(item.get("key") or item.get("id") or "")
    return {
        "id": model_id,
        "name": str(item.get("display_name") or model_id),
        "loaded": _loaded(item),
        "tools": _tools(item),
    }


def _parse(data: object) -> list[dict[str, Any]] | None:
    """Модели для разговора из ответа (models или data); не список моделей — None."""
    items = cast(dict[str, Any], data).get("models", data.get("data")) if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    raw = [cast(dict[str, Any], i) for i in cast(list[object], items) if isinstance(i, dict)]
    models = [model_entry(i) for i in raw if i.get("type") not in _SKIPPED_TYPES]
    return sorted(
        (m for m in models if m["id"]), key=lambda m: (m["loaded"] is not True, str(m["name"]).casefold())
    )


async def _try(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> list[dict[str, Any]] | None:
    """Модели по одному пути; путь не отвечает списком — None; ключ не принят — ExecutorError."""
    response = await client.get(url, headers=headers)
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise ExecutorError("LM Studio не принял ключ — проверьте ключ в настройках ядра")
    if response.status_code != httpx.codes.OK:
        return None
    try:
        return _parse(response.json())
    except ValueError:
        return None


async def fetch_lmstudio_models(
    base_url: str, api_key: str, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Модели LM Studio (загруженные — первыми); сервер не запущен или не отдал список — ExecutorError.

    client — свой HTTP-клиент (тесты); свой по умолчанию закрывается после запроса.
    """
    server = server_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    http = client if client is not None else httpx.AsyncClient(timeout=LIST_TIMEOUT_S)
    try:
        for path in MODEL_PATHS:
            models = await _try(http, server + path, headers)
            if models is not None:
                return models
    except httpx.HTTPError as exc:
        raise connect_error(server, exc) from exc
    finally:
        if client is None:
            await http.aclose()
    raise ExecutorError(f"LM Studio по адресу {server} не отдал список моделей")


def with_lmstudio(
    fetch: Callable[[str], Awaitable[frozenset[str]]],
) -> Callable[[str], Awaitable[frozenset[str]]]:
    """Возможности модели: «@lmstudio/…» — LMSTUDIO_CAPABILITIES без запроса, остальные — fetch."""

    async def capabilities(model: str) -> frozenset[str]:
        if model.startswith(LMSTUDIO_MODEL_PREFIX):
            return LMSTUDIO_CAPABILITIES
        return await fetch(model)

    return capabilities
