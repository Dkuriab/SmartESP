"""Тесты list_models и loaded_models."""

from types import SimpleNamespace
from typing import Any

import httpx
import ollama
import pytest

from smartesp.contracts import ExecutorError
from smartesp.executors import list_models, loaded_models


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
