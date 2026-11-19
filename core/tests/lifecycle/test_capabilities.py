"""Кеш возможностей моделей: запоминает известное, пустое спрашивает снова, ошибки глотает."""

from __future__ import annotations

from smartesp.lifecycle import CapabilityCache


async def test_capability_cache_keeps_known_and_retries_empty() -> None:
    calls: list[str] = []

    async def fetch(model: str) -> frozenset[str]:
        calls.append(model)
        return frozenset() if model == "gone" else frozenset({"completion", "tools"})

    cache = CapabilityCache(fetch)
    assert await cache.supports_tools("small") and await cache.supports_tools("small")
    assert not await cache.supports_tools("gone") and not await cache.supports_tools("gone")
    assert calls == ["small", "gone", "gone"]  # пустое не запоминается: модель могут скачать
    assert cache.known("small") == frozenset({"completion", "tools"}) and cache.known("gone") == frozenset()


async def test_capability_cache_swallows_errors() -> None:
    async def broken(model: str) -> frozenset[str]:
        raise RuntimeError("ollama упала")

    assert await CapabilityCache(broken).get("small") == frozenset()
