"""Тесты инструментов и возможностей модели в Ollama."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx

from smartesp.contracts import ChatMessage, Identified, ToolCall, ToolSpec, UsesModels
from smartesp.executors import OllamaExecutor, model_capabilities

SPEC = ToolSpec("delegate", "Передать задачу.", {"type": "object", "properties": {}})


class ToolClient:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.chat_kwargs: dict[str, Any] = {}

    async def chat(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.chat_kwargs = kwargs
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        for c in self.chunks:
            yield c


def obj_call(name: str, args: dict[str, Any]) -> Any:
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=args))


def obj_chunk(text: str = "", calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls))


async def run(ex: OllamaExecutor, tools: tuple[ToolSpec, ...] = ()) -> list[Any]:
    return [p async for p in ex.run([ChatMessage("user", "привет")], tools)]


async def test_tools_passed_to_chat() -> None:
    c = ToolClient([obj_chunk("x")])
    await run(OllamaExecutor("m", "s", "1m", c), (SPEC,))
    assert c.chat_kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "delegate",
                "description": "Передать задачу.",
                "parameters": SPEC.parameters,
            },
        }
    ]


async def test_no_tools_key_without_tools() -> None:
    c = ToolClient([obj_chunk("x")])
    await run(OllamaExecutor("m", "s", "1m", c))
    assert "tools" not in c.chat_kwargs


async def test_text_then_tool_call() -> None:
    c = ToolClient([obj_chunk("Сейчас спрошу."), obj_chunk("", [obj_call("delegate", {"task": "t"})])])
    parts = await run(OllamaExecutor("m", "s", "1m", c), (SPEC,))
    assert [p.text for p in parts if p.text] == ["Сейчас спрошу."]
    assert [p.tool_call for p in parts if p.tool_call] == [ToolCall("delegate", {"task": "t"})]


async def test_dict_format() -> None:
    call = {"function": {"name": "delegate", "arguments": {"task": "t"}}}
    c = ToolClient([{"message": {"content": "", "tool_calls": [call]}}])
    parts = await run(OllamaExecutor("m", "s", "1m", c), (SPEC,))
    assert [p.tool_call for p in parts] == [ToolCall("delegate", {"task": "t"})]


def test_id_models_and_unload() -> None:
    ex = OllamaExecutor("m", "s", "1m", ToolClient([]), id="fast")
    assert isinstance(ex, Identified) and ex.id == "fast"
    assert isinstance(ex, UsesModels)
    assert ex.models() == frozenset({"m"})


async def test_unload_models_only_when_named() -> None:
    calls: list[Any] = []

    class C:
        async def generate(self, **kw: Any) -> None:
            calls.append(kw)

    ex = OllamaExecutor("m", "s", "1m", C())
    await ex.unload_models(["other"])
    assert calls == []
    await ex.unload_models(["m"])
    assert calls[0]["model"] == "m" and calls[0]["keep_alive"] == 0


class ShowClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def show(self, model: str) -> Any:
        if self.error:
            raise self.error
        return self.response


async def test_capabilities_parsed() -> None:
    c = ShowClient(SimpleNamespace(capabilities=["completion", "tools"]))
    assert await model_capabilities("m", c) == frozenset({"completion", "tools"})
    assert await model_capabilities("m", ShowClient({"capabilities": ["tools"]})) == {"tools"}


async def test_capabilities_error_is_empty() -> None:
    c = ShowClient(error=httpx.ConnectError("down"))
    assert await model_capabilities("m", c) == frozenset()
    assert await model_capabilities("m", ShowClient(SimpleNamespace(capabilities=None))) == set()
