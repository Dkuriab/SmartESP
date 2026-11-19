"""Тесты GET /core, POST /core/stop и POST /models/unload."""

from __future__ import annotations

import httpx
import pytest

from fakes.fake_core import FakeCore
from smartesp.contracts import ExecutorError

from .conftest import HEADERS, PORT

P = "/api/v1"


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/core"), ("POST", "/core/stop"), ("POST", "/models/unload")]
)
async def test_routes_require_token(
    client: httpx.AsyncClient, core: FakeCore, method: str, path: str
) -> None:
    response = await client.request(method, f"{P}{path}", json={"name": "qwen3:8b"})
    assert response.status_code == 401
    assert core.stops == 0 and core.unloaded == []


async def test_core_info(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{P}/core", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "version": "0.1.0",
        "uptime_s": 12.5,
        "state": "ready",
        "port": PORT,
        "data_dir": "/tmp/smartesp",
    }


async def test_stop_is_post_only(client: httpx.AsyncClient, core: FakeCore) -> None:
    assert (await client.get(f"{P}/core/stop", headers=HEADERS)).status_code == 405
    response = await client.post(f"{P}/core/stop", headers=HEADERS)
    assert response.status_code == 202
    assert core.stops == 1 and core.restarts == 0


@pytest.mark.parametrize("name", ["qwen3:8b", "hf.co/user/model:Q4"])
async def test_unload_loaded_model(client: httpx.AsyncClient, core: FakeCore, name: str) -> None:
    response = await client.post(f"{P}/models/unload", headers=HEADERS, json={"name": name})
    assert response.status_code == 204
    assert core.unloaded == [name]


async def test_unload_not_loaded_is_404(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.post(f"{P}/models/unload", headers=HEADERS, json={"name": "llama3"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Модель не загружена"}
    assert core.unloaded == []


async def test_unload_without_ollama_is_502(client: httpx.AsyncClient, core: FakeCore) -> None:
    core.unload_error = ExecutorError("Ollama недоступна")
    response = await client.post(f"{P}/models/unload", headers=HEADERS, json={"name": "qwen3:8b"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Ollama недоступна"}


@pytest.mark.parametrize("name", ["", "a\nb", "x" * 201, None])
async def test_unload_rejects_bad_name(client: httpx.AsyncClient, core: FakeCore, name: object) -> None:
    response = await client.post(f"{P}/models/unload", headers=HEADERS, json={"name": name})
    assert response.status_code == 422
    assert core.unloaded == []
