"""Тесты OllamaExecutor."""

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import ollama
import pytest

from smartesp.contracts import ChatMessage, Executor, ExecutorError
from smartesp.executors import OllamaExecutor


class FakeClient:
    def __init__(self, parts: list[str] | None = None, error: Exception | None = None) -> None:
        self.parts = parts or []
        self.error = error
        self.chat_kwargs: dict[str, Any] = {}
        self.generate_kwargs: dict[str, Any] = {}

    async def chat(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.chat_kwargs = kwargs
        if self.error:
            raise self.error
        return self._stream()

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        for p in self.parts:
            yield {"message": {"content": p}}

    async def generate(self, **kwargs: Any) -> None:
        self.generate_kwargs = kwargs
        if self.error:
            raise self.error


def make(client: FakeClient) -> OllamaExecutor:
    return OllamaExecutor("m", "Ты помощник.", "30m", client)


async def collect(ex: OllamaExecutor) -> list[str]:
    return [p.text async for p in ex.run([ChatMessage("user", "привет")])]


def test_satisfies_executor_protocol() -> None:
    ex: Executor = make(FakeClient())
    assert ex is not None


async def test_streams_parts_skipping_empty() -> None:
    assert await collect(make(FakeClient(["При", "", "вет"]))) == ["При", "вет"]


async def test_prepends_system_prompt() -> None:
    c = FakeClient(["x"])
    await collect(make(c))
    msgs = c.chat_kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "Ты помощник."}
    assert msgs[1] == {"role": "user", "content": "привет"}


async def test_passes_think_false_and_keep_alive() -> None:
    c = FakeClient(["x"])
    await collect(make(c))
    assert c.chat_kwargs["think"] is False
    assert c.chat_kwargs["keep_alive"] == "30m"
    assert c.chat_kwargs["stream"] is True
    assert c.chat_kwargs["model"] == "m"


async def test_connection_error_becomes_executor_error() -> None:
    with pytest.raises(ExecutorError, match="m"):
        await collect(make(FakeClient(error=httpx.ConnectError("нет связи"))))


async def test_missing_model_becomes_executor_error() -> None:
    with pytest.raises(ExecutorError, match="ollama pull"):
        await collect(make(FakeClient(error=ollama.ResponseError("not found", 404))))


async def test_warm_up_calls_generate_and_wraps_errors() -> None:
    c = FakeClient()
    await make(c).warm_up()
    assert c.generate_kwargs["keep_alive"] == "30m"
    with pytest.raises(ExecutorError):
        await make(FakeClient(error=httpx.ConnectError("x"))).warm_up()


@pytest.mark.models
async def test_real_ollama_streams_answer() -> None:
    model = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"
    ex = OllamaExecutor(model, "Отвечай кратко.", "5m")
    await ex.warm_up()
    start = time.monotonic()
    first: float | None = None
    text = ""
    async for part in ex.run([ChatMessage("user", "Ответь одним словом: столица Франции?")]):
        if first is None:
            first = time.monotonic() - start
        text += part.text
    print(f"\nanswer={text!r} first_token={first:.2f}s total={time.monotonic() - start:.2f}s")
    assert "париж" in text.lower()
