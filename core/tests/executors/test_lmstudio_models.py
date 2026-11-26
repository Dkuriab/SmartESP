"""Список моделей LM Studio на подделке сервера: три формата, запасные пути, ошибки, возможности."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from smartesp.contracts import ExecutorError
from smartesp.executors import fetch_lmstudio_models, with_lmstudio
from smartesp.executors.lmstudio_models import LMSTUDIO_CAPABILITIES

V1 = {
    "models": [
        {
            "type": "llm",
            "key": "qwen/qwen3-8b",
            "display_name": "Qwen3 8B",
            "loaded_instances": [],
            "capabilities": {"vision": False, "trained_for_tool_use": True},
        },
        {
            "type": "llm",
            "key": "google/gemma-3-12b",
            "display_name": "Gemma 3 12B",
            "loaded_instances": [{"id": "google/gemma-3-12b", "config": {}}],
            "capabilities": {"vision": True, "trained_for_tool_use": False},
        },
        {"type": "embedding", "key": "nomic-embed", "display_name": "Nomic", "loaded_instances": []},
    ]
}
V0 = {
    "object": "list",
    "data": [
        {"id": "qwen/qwen3-8b", "type": "llm", "state": "not-loaded", "capabilities": ["tool_use"]},
        {"id": "mistral-7b", "type": "llm", "state": "loaded"},
        {"id": "text-embedding-nomic", "type": "embeddings", "state": "not-loaded"},
    ],
}
OPENAI = {
    "object": "list",
    "data": [{"id": "qwen/qwen3-8b", "object": "model", "owned_by": "organization_owner"}],
}


def _client(routes: dict[str, object], seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = routes.get(request.url.path)
        return (
            httpx.Response(404, json={"error": "Unexpected endpoint"})
            if body is None
            else httpx.Response(200, json=body)
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_v1_rest_api_marks_loaded_and_native_tools_loaded_first() -> None:
    seen: list[httpx.Request] = []
    models = await fetch_lmstudio_models(
        "http://localhost:1234/v1", "lm-key", _client({"/api/v1/models": V1}, seen)
    )
    assert models == [
        {"id": "google/gemma-3-12b", "name": "Gemma 3 12B", "loaded": True, "tools": False},
        {"id": "qwen/qwen3-8b", "name": "Qwen3 8B", "loaded": False, "tools": True},
    ]
    assert str(seen[0].url) == "http://localhost:1234/api/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer lm-key"


async def test_falls_back_to_v0_then_openai_list() -> None:
    v0 = await fetch_lmstudio_models("http://localhost:1234", "", _client({"/api/v0/models": V0}))
    assert v0 == [
        {"id": "mistral-7b", "name": "mistral-7b", "loaded": True, "tools": None},
        {"id": "qwen/qwen3-8b", "name": "qwen/qwen3-8b", "loaded": False, "tools": True},
    ]
    seen: list[httpx.Request] = []
    plain = await fetch_lmstudio_models("http://localhost:1234", "", _client({"/v1/models": OPENAI}, seen))
    assert plain == [{"id": "qwen/qwen3-8b", "name": "qwen/qwen3-8b", "loaded": None, "tools": None}]
    assert [r.url.path for r in seen] == ["/api/v1/models", "/api/v0/models", "/v1/models"]
    assert "Authorization" not in seen[0].headers


async def test_server_not_running_and_rejected_key_are_plain_errors() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    with pytest.raises(ExecutorError, match="Сервер LM Studio не запущен по адресу http://mac.local:1234"):
        await fetch_lmstudio_models("http://mac.local:1234", "", client)

    def locked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    with pytest.raises(ExecutorError, match="не принял ключ"):
        await fetch_lmstudio_models(
            "http://localhost:1234", "x", httpx.AsyncClient(transport=httpx.MockTransport(locked))
        )


async def test_nothing_answers_is_plain_error() -> None:
    with pytest.raises(ExecutorError, match="не отдал список моделей"):
        await fetch_lmstudio_models("http://localhost:1234", "", _client({"/api/v1/models": "не список"}))


async def test_lmstudio_models_skip_ollama() -> None:
    asked: list[str] = []

    async def ollama(model: str) -> frozenset[str]:
        asked.append(model)
        return frozenset({"completion"})

    caps: Callable[[str], Any] = with_lmstudio(ollama)
    assert await caps("@lmstudio/qwen/qwen3-8b") == LMSTUDIO_CAPABILITIES
    assert await caps("gpt-oss:20b") == frozenset({"completion"})
    assert asked == ["gpt-oss:20b"]
