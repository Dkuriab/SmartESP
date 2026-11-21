"""Модели облачного сервиса: список для интерфейса (с кэшем) и возможности для сети исполнителей."""

import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from smartesp.contracts import CLOUD_MODEL_PREFIX, ExecutorError

LIST_TIMEOUT_S = 10.0
CACHE_S = 600.0  # список моделей меняется редко, а у OpenRouter он большой
# облачная модель в сети: инструменты считаем доступными (список моделей показывает, у какой их нет)
CLOUD_CAPABILITIES = frozenset({"completion", "tools"})

type Fetch = Callable[[str, str], Awaitable[list[dict[str, Any]]]]


def _per_million(value: object) -> float | None:
    """Цена за 1 млн токенов из цены за токен (строка «0.0000001»); неизвестно или < 0 — None."""
    try:
        price = float(cast(str, value))
    except (TypeError, ValueError):
        return None
    return round(price * 1_000_000, 4) if price >= 0 else None


def model_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Модель из ответа /models: {id, name, tools, prompt_price, completion_price} (цены — $ за 1 млн)."""
    pricing = cast(dict[str, Any], item.get("pricing") or {})
    params = item.get("supported_parameters")
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or ""),
        # список параметров не дан (не OpenRouter) — считаем, что умеет
        "tools": "tools" in params if isinstance(params, list) else True,
        "prompt_price": _per_million(pricing.get("prompt")),
        "completion_price": _per_million(pricing.get("completion")),
    }


async def fetch_models(base_url: str, api_key: str) -> list[dict[str, Any]]:
    """Модели сервиса по имени; сбой — ExecutorError (ключ не обязателен: у OpenRouter список открыт)."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_S) as client:
            response = await client.get(base_url.rstrip("/") + "/models", headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExecutorError(f"Не удалось получить список облачных моделей: {type(exc).__name__}") from exc
    items = data.get("data") if isinstance(data, dict) else None
    models = [model_entry(cast(dict[str, Any], i)) for i in items or [] if isinstance(i, dict)]
    return sorted((m for m in models if m["id"]), key=lambda m: str(m["name"]).casefold())


class CloudCatalog:
    """Список моделей облачного сервиса с кэшем на CACHE_S секунд (по адресу сервиса)."""

    def __init__(self, fetch: Fetch = fetch_models, clock: Callable[[], float] = time.monotonic) -> None:
        """fetch(адрес, ключ) — запрос списка; clock — часы для срока кэша."""
        self._fetch = fetch
        self._clock = clock
        self._cached: tuple[str, float, list[dict[str, Any]]] | None = None

    async def models(self, base_url: str, api_key: str) -> list[dict[str, Any]]:
        """Модели сервиса (из кэша, если свежий); сбой — ExecutorError."""
        now = self._clock()
        if self._cached is not None and self._cached[0] == base_url and now - self._cached[1] < CACHE_S:
            return self._cached[2]
        models = await self._fetch(base_url, api_key)
        self._cached = (base_url, now, models)
        return models


def with_cloud(
    fetch: Callable[[str], Awaitable[frozenset[str]]],
) -> Callable[[str], Awaitable[frozenset[str]]]:
    """Возможности модели: «@cloud/…» — CLOUD_CAPABILITIES без запроса, остальные — fetch (Ollama)."""

    async def capabilities(model: str) -> frozenset[str]:
        if model.startswith(CLOUD_MODEL_PREFIX):
            return CLOUD_CAPABILITIES
        return await fetch(model)

    return capabilities
