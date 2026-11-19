"""Тесты инструментов через клиентскую сессию SDK в памяти."""

import pytest
from mcp import Client
from mcp.types import TextContent

from calc_mcp.server import build_server


async def call(name: str, args: dict[str, object]) -> tuple[bool, str]:
    async with Client(build_server()) as client:
        result = await client.call_tool(name, args)
    block = result.content[0]
    assert isinstance(block, TextContent)
    return result.is_error, block.text


async def test_tools_listed_in_russian() -> None:
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {"calculate", "convert", "split"}
    for tool in tools:
        assert tool.description
        assert any("а" <= ch.lower() <= "я" for ch in tool.description)


async def test_calculate() -> None:
    assert await call("calculate", {"expression": "101 / 2"}) == (False, "50,5")


async def test_calculate_error_is_tool_error() -> None:
    is_error, text = await call("calculate", {"expression": "1 / 0"})
    assert is_error
    assert "ноль" in text


async def test_calculate_dangerous() -> None:
    is_error, text = await call("calculate", {"expression": "__import__('os')"})
    assert is_error
    assert "не понял" in text.lower()


async def test_convert() -> None:
    args = {"value": 1, "from_unit": "стакан", "to_unit": "г", "product": "мука"}
    assert await call("convert", args) == (False, "1 стакан — это 132,5 грамма (мука)")


async def test_convert_refusal() -> None:
    args = {"value": 1, "from_unit": "стакан", "to_unit": "г"}
    is_error, text = await call("convert", args)
    assert is_error
    assert "продукт" in text


async def test_split() -> None:
    args = {"total": 500, "parts": 10, "unit": "г"}
    assert await call("split", args) == (False, "500 граммов на 10 — по 50 граммов")


async def test_split_error() -> None:
    is_error, text = await call("split", {"total": 5, "parts": 0})
    assert is_error
    assert "частей" in text


async def test_works_without_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """calc не хранит данных: переменная SMARTESP_CONNECTOR_DATA не нужна."""
    monkeypatch.delenv("SMARTESP_CONNECTOR_DATA", raising=False)
    assert await call("calculate", {"expression": "1+1"}) == (False, "2")


async def test_calculate_exact_big_integer() -> None:
    assert await call("calculate", {"expression": "3 ** 60"}) == (False, "42391158275216203514294433201")
