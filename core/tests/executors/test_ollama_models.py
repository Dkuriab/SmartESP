"""Тесты list_models и loaded_models."""

from types import SimpleNamespace
from typing import Any

import httpx
import ollama
import pytest

from smartesp.contracts import ExecutorError
from smartesp.executors import list_models, loaded_models, unload_model


class FakeClient:
    def __init__(self, listed: Any = None, running: Any = None, error: Exception | None = None):
        self.listed = listed
        self.running = running
        self.error = error

    async def list(self) -> Any:
        if self.error:
            raise self.error
        return self.listed

    async def ps(self) -> Any:
        if self.error:
            raise self.error
        return self.running


async def test_list_models_objects() -> None:
    resp = SimpleNamespace(
        models=[SimpleNamespace(model="a:1", size=10), SimpleNamespace(model="b", size=None)]
    )
    assert await list_models(FakeClient(listed=resp)) == [("a:1", 10), ("b", 0)]


async def test_list_models_dicts() -> None:
    resp = {"models": [{"model": "a:1", "size": 10}, {"name": "c", "size": 5}]}
    assert await list_models(FakeClient(listed=resp)) == [("a:1", 10), ("c", 5)]


async def test_loaded_models_objects_and_dicts() -> None:
    resp = SimpleNamespace(models=[SimpleNamespace(model="a:1"), {"model": "b"}])
    assert await loaded_models(FakeClient(running=resp)) == ["a:1", "b"]


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("x"), ConnectionError("x"), ollama.ResponseError("bad")]
)
async def test_errors_become_executor_error(error: Exception) -> None:
    with pytest.raises(ExecutorError):
        await list_models(FakeClient(error=error))
    with pytest.raises(ExecutorError):
        await loaded_models(FakeClient(error=error))


class ClosableClient(FakeClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.parametrize("fail", [False, True])
async def test_own_client_is_closed(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    created: list[ClosableClient] = []

    def factory(**_: Any) -> ClosableClient:
        c = ClosableClient(
            listed={"models": []},
            running={"models": []},
            error=httpx.ConnectError("x") if fail else None,
        )
        created.append(c)
        return c

    monkeypatch.setattr(ollama, "AsyncClient", factory)
    for fn in (list_models, loaded_models):
        if fail:
            with pytest.raises(ExecutorError):
                await fn()
        else:
            await fn()
    assert len(created) == 2
    assert [c.closed for c in created] == [1, 1]


async def test_injected_client_not_closed() -> None:
    c = ClosableClient(listed={"models": []}, running={"models": []})
    await list_models(c)
    await loaded_models(c)
    assert c.closed == 0


class GenerateClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {}


async def test_unload_model_sends_keep_alive_zero() -> None:
    client = GenerateClient()
    await unload_model("hf.co/a/b:Q4", client)
    assert client.calls == [{"model": "hf.co/a/b:Q4", "prompt": "", "keep_alive": 0}]


@pytest.mark.parametrize("error", [httpx.ConnectError("x"), ollama.ResponseError("bad")])
async def test_unload_model_errors_become_executor_error(error: Exception) -> None:
    with pytest.raises(ExecutorError):
        await unload_model("qwen", GenerateClient(error))
