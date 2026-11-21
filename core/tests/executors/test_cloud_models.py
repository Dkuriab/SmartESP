"""Модели облачного сервиса: разбор списка, кэш, возможности для сети исполнителей."""

from typing import Any

from smartesp.executors import CloudCatalog, with_cloud
from smartesp.executors.cloud_models import CLOUD_CAPABILITIES, model_entry


def test_model_entry_prices_per_million_and_tools() -> None:
    item = {
        "id": "google/gemini-2.5-flash",
        "name": "Google: Gemini 2.5 Flash",
        "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
        "supported_parameters": ["tools", "reasoning"],
    }
    assert model_entry(item) == {
        "id": "google/gemini-2.5-flash",
        "name": "Google: Gemini 2.5 Flash",
        "tools": True,
        "prompt_price": 0.3,
        "completion_price": 2.5,
    }
    router = model_entry({"id": "openrouter/auto", "pricing": {"prompt": "-1"}, "supported_parameters": []})
    assert router["tools"] is False and router["prompt_price"] is None and router["name"] == "openrouter/auto"
    assert model_entry({"id": "x"})["tools"] is True  # не OpenRouter: параметров нет — считаем, что умеет


async def test_catalog_caches_by_address_for_ten_minutes() -> None:
    calls: list[str] = []
    now = [0.0]

    async def fetch(base_url: str, api_key: str) -> list[dict[str, Any]]:
        calls.append(base_url)
        return [{"id": base_url}]

    catalog = CloudCatalog(fetch, clock=lambda: now[0])
    await catalog.models("a", "")
    now[0] = 599.0
    await catalog.models("a", "")
    await catalog.models("b", "")
    now[0] = 1300.0
    await catalog.models("b", "")
    assert calls == ["a", "b", "b"]


async def test_cloud_models_skip_ollama() -> None:
    asked: list[str] = []

    async def ollama(model: str) -> frozenset[str]:
        asked.append(model)
        return frozenset({"completion"})

    caps = with_cloud(ollama)
    assert await caps("@cloud/google/gemini-2.5-flash") == CLOUD_CAPABILITIES
    assert await caps("gpt-oss:20b") == frozenset({"completion"})
    assert asked == ["gpt-oss:20b"]
