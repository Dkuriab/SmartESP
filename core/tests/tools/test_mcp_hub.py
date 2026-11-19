"""Хаб: инструменты, вызовы, ошибки, сообщения коннектора, совпадение имён."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from mcp_hub_helpers import spec, state, tool_pid, wait_until
from mcp_test_server import LONG_TOOL

from smartesp.contracts import DELEGATE_TOOL, ToolBox, ToolResult
from smartesp.tools import McpHub


@pytest.fixture
async def hub(tmp_path: Path) -> AsyncIterator[McpHub]:
    hub = McpHub(tmp_path, call_timeout_s=1.0)
    yield hub
    await hub.aclose()


async def test_tools_are_visible_and_callable(hub: McpHub, tmp_path: Path):
    await hub.start([spec("a")])
    box: ToolBox = hub  # McpHub реализует договор (проверяет pyright)
    st = state(hub, "a")
    assert (st.state, st.name, st.error) == ("ready", "A", "")
    assert "echo" in st.tools
    echo = next(s for s in hub.specs() if s.name == "echo")
    assert echo.description == "Повторяет текст"
    assert echo.parameters["required"] == ["text"]
    assert await box.call("echo", {"text": "привет"}, None) == ToolResult("привет")


async def test_person_goes_to_meta(hub: McpHub):
    await hub.start([spec("a")])
    assert (await hub.call("whoami", {}, "Даша")).text == "Даша"
    assert (await hub.call("whoami", {}, None)).text == "никто"


async def test_environment_and_data_dir(hub: McpHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMARTESP_TEST_CORE_ENV", "ядро")
    await hub.start([spec("a", FOO="bar")])
    data = tmp_path / "connectors" / "a"
    assert (await hub.call("env", {"name": "FOO"}, None)).text == f"{data}|True|bar"
    assert (await hub.call("env", {"name": "SMARTESP_TEST_CORE_ENV"}, None)).text.endswith("|ядро")


async def test_tool_error_is_error_result(hub: McpHub):
    await hub.start([spec("a")])
    result = await hub.call("fail", {}, None)
    assert result.is_error
    assert result.text


async def test_unknown_tool_is_error(hub: McpHub):
    await hub.start([spec("a")])
    result = await hub.call("nope", {}, None)
    assert result.is_error
    assert "nope" in result.text


async def test_hanging_call_times_out_and_connector_survives(hub: McpHub):
    await hub.start([spec("a")])
    result = await hub.call("sleep", {"seconds": 10}, None)
    assert result.is_error
    assert result.text == "Коннектор «A» не отвечает."
    assert (await hub.call("echo", {"text": "жив"}, None)).text == "жив"


async def test_announce_reaches_callback(tmp_path: Path):
    got: list[tuple[str, str | None, str]] = []
    hub = McpHub(tmp_path, on_announce=lambda text, person, cid: got.append((text, person, cid)))
    try:
        await hub.start([spec("a")])
        await hub.call("announce", {"text": "Время вышло.", "person": "Даша"}, None)
        await hub.call("announce", {"text": "Всем.", "person": None}, None)
        await wait_until(lambda: len(got) == 2)
        assert got == [("Время вышло.", "Даша", "a"), ("Всем.", None, "a")]
    finally:
        await hub.aclose()


async def test_announce_outside_tool_call_reaches_callback(tmp_path: Path):
    got: list[tuple[str, str | None, str]] = []
    hub = McpHub(tmp_path, on_announce=lambda text, person, cid: got.append((text, person, cid)))
    try:
        await hub.start([spec("a")])
        result = await hub.call("announce_later", {"text": "Таймер: время вышло.", "seconds": 0.3}, None)
        assert result.text == "объявлю позже"
        assert got == []
        await wait_until(lambda: len(got) == 1)
        assert got == [("Таймер: время вышло.", None, "a")]
    finally:
        await hub.aclose()


async def test_failing_announce_callback_does_not_break_hub(tmp_path: Path):
    def boom(text: str, person: str | None, cid: str) -> None:
        raise RuntimeError("сломался обработчик")

    hub = McpHub(tmp_path, on_announce=boom)
    try:
        await hub.start([spec("a")])
        assert (await hub.call("announce", {"text": "x", "person": None}, None)).text == "объявил"
        assert (await hub.call("echo", {"text": "жив"}, None)).text == "жив"
    finally:
        await hub.aclose()


async def test_other_log_goes_to_core_log(hub: McpHub, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="smartesp.tools")
    await hub.start([spec("a")])
    await hub.call("log", {"text": "диск почти полон"}, None)
    await wait_until(lambda: any("диск почти полон" in r.getMessage() for r in caplog.records))
    record = next(r for r in caplog.records if "диск почти полон" in r.getMessage())
    assert record.levelno == logging.WARNING
    assert "a" in record.getMessage()


async def test_name_collision_prefixes_second(hub: McpHub, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="smartesp.tools")
    await hub.start([spec("a"), spec("b")])
    names = [s.name for s in hub.specs()]
    assert len(names) == len(set(names))
    assert {"echo", "b_echo", "pid", "b_pid"} <= set(names)
    assert "b_echo" in state(hub, "b").tools
    assert await tool_pid(hub, "pid") != await tool_pid(hub, "b_pid")
    assert any("b_echo" in r.getMessage() for r in caplog.records)


async def test_garbage_on_stdout_is_tolerated(hub: McpHub):
    await hub.start([spec("a", "garbage")])
    assert state(hub, "a").state == "ready"
    assert (await hub.call("echo", {"text": "ok"}, None)).text == "ok"


async def test_model_names_are_safe_and_delegate_is_reserved(hub: McpHub, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="smartesp.tools")
    await hub.start([spec("a"), spec("b")])
    names = [s.name for s in hub.specs()]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in names)
    assert DELEGATE_TOOL not in names
    assert {"a_delegate", "b_delegate", "notes_add", "b_notes_add", LONG_TOOL} <= set(names)
    assert (await hub.call("a_delegate", {}, None)).text == "делегат коннектора"
    assert (await hub.call("notes_add", {}, None)).text == "с точкой"
    long_b = next(n for n in names if n.startswith("b_l") and n != f"b_{LONG_TOOL}")
    assert len(long_b) == 64
    assert await tool_pid(hub, long_b) == await tool_pid(hub, "b_pid")
    assert await tool_pid(hub, LONG_TOOL) == await tool_pid(hub, "pid")
    assert any("a_delegate" in r.getMessage() for r in caplog.records)
