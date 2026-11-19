"""Хаб: запуск, падение и перезапуск, применение настроек, остановка без сирот."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path

from mcp_hub_helpers import alive, file_pid, spec, state, tool_pid, wait_until

from smartesp.tools import McpHub


async def test_crashed_connector_fails_then_restarts_by_delays(tmp_path: Path):
    hub = McpHub(tmp_path, restart_delays_s=(0.3, 2.0))
    try:
        await hub.start([spec("a")])
        first = await tool_pid(hub)
        crash = await hub.call("crash", {}, None)
        assert crash.is_error
        await wait_until(lambda: state(hub, "a").state == "failed")
        assert state(hub, "a").error
        assert state(hub, "a").tools == ()
        assert hub.specs() == []
        unavailable = await hub.call("echo", {"text": "x"}, None)
        assert unavailable.is_error
        assert "«A»" in unavailable.text
        await wait_until(lambda: state(hub, "a").state == "ready")
        second = await tool_pid(hub)
        assert second != first
        assert not alive(first)
        # второе падение подряд — следующая задержка (2 с), а не первая
        await hub.call("crash", {}, None)
        await wait_until(lambda: state(hub, "a").state == "failed")
        await asyncio.sleep(1.0)
        assert state(hub, "a").state == "failed"
        await wait_until(lambda: state(hub, "a").state == "ready")
        assert await tool_pid(hub) not in (first, second)
    finally:
        await hub.aclose()


async def test_connector_that_never_starts_is_failed_and_others_work(tmp_path: Path):
    hub = McpHub(tmp_path, start_timeout_s=1.0, restart_delays_s=(60.0,))
    try:
        began = time.monotonic()
        await hub.start([spec("hang", "hang"), spec("exit", "exit"), spec("ok")])
        assert time.monotonic() - began < 8.0
        assert state(hub, "hang").state == "failed"
        assert state(hub, "exit").state == "failed"
        assert state(hub, "hang").error and state(hub, "exit").error
        assert (await hub.call("echo", {"text": "ok"}, None)).text == "ok"
    finally:
        await hub.aclose()


async def test_missing_command_is_failed(tmp_path: Path):
    hub = McpHub(tmp_path, restart_delays_s=(60.0,))
    try:
        await hub.start([replace(spec("bad"), command="/nonexistent/connector")])
        assert state(hub, "bad").state == "failed"
        assert state(hub, "bad").error
    finally:
        await hub.aclose()


async def test_apply_restarts_only_changed(tmp_path: Path):
    hub = McpHub(tmp_path)
    try:
        await hub.start([spec("a"), spec("b")])
        a1, b1 = await tool_pid(hub, "pid"), await tool_pid(hub, "b_pid")
        await hub.apply([spec("a"), spec("b", FOO="new")])
        assert await tool_pid(hub, "pid") == a1
        b2 = await tool_pid(hub, "b_pid")
        assert b2 != b1
        assert not alive(b1)
        await hub.apply([spec("a"), spec("b", FOO="new", enabled=False)])
        assert state(hub, "b").state == "disabled"
        assert state(hub, "b").tools == ()
        assert not alive(b2)
        await hub.apply([spec("a")])
        assert [s.id for s in hub.states()] == ["a"]
        assert await tool_pid(hub) == a1
    finally:
        await hub.aclose()


async def test_disabled_connector_is_not_started(tmp_path: Path):
    hub = McpHub(tmp_path)
    try:
        await hub.start([spec("a", enabled=False)])
        st = state(hub, "a")
        assert (st.state, st.tools, st.error) == ("disabled", (), "")
        assert not (tmp_path / "connectors" / "a" / "pid").exists()
        assert hub.specs() == []
    finally:
        await hub.aclose()


async def test_aclose_leaves_no_processes(tmp_path: Path):
    hub = McpHub(tmp_path, start_timeout_s=1.0, restart_delays_s=(60.0,))
    await hub.start([spec("a"), spec("b"), spec("hang", "hang")])
    pids = [await tool_pid(hub, "pid"), await tool_pid(hub, "b_pid"), file_pid(tmp_path, "hang")]
    await hub.aclose()
    assert not any(alive(pid) for pid in pids)
    result = await hub.call("echo", {"text": "x"}, None)
    assert result.is_error


async def test_aclose_during_startup_leaves_no_processes(tmp_path: Path):
    hub = McpHub(tmp_path, start_timeout_s=30.0)
    starting = asyncio.create_task(hub.start([spec("hang", "hang")]))
    await wait_until(lambda: (tmp_path / "connectors" / "hang" / "pid").exists())
    assert state(hub, "hang").state == "starting"
    pid = file_pid(tmp_path, "hang")
    began = time.monotonic()
    await hub.aclose()
    await starting
    assert time.monotonic() - began < 10.0
    assert not alive(pid)


async def test_on_tools_called_when_ready_tools_change(tmp_path: Path):
    seen: list[list[str]] = []
    hub = McpHub(tmp_path, on_tools=lambda: seen.append([t.name for t in hub.specs()]))
    try:
        await hub.start([spec("a")])
        assert seen and "echo" in seen[-1]
        count = len(seen)
        await hub.apply([spec("a")])  # ничего не изменилось — не зовём
        assert len(seen) == count
        await hub.apply([spec("a", enabled=False)])
        assert seen[-1] == []
    finally:
        await hub.aclose()


async def test_apply_soon_starts_in_background(tmp_path: Path):
    hub = McpHub(tmp_path)
    try:
        hub.apply_soon([spec("a")])
        assert hub.specs() == []  # ещё не запущен: вызов не ждёт
        await wait_until(lambda: state(hub, "a").state == "ready" if hub.states() else False)
        assert (await hub.call("echo", {"text": "да"}, None)).text == "да"
        hub.apply_soon([spec("a", enabled=False)])
        hub.apply_soon([spec("a"), spec("b")])  # по порядку: последняя правка побеждает
        await wait_until(lambda: [s.state for s in hub.states()] == ["ready", "ready"])
    finally:
        await hub.aclose()


async def test_aclose_cancels_pending_apply_and_ignores_later(tmp_path: Path):
    hub = McpHub(tmp_path, start_timeout_s=30.0)
    hub.apply_soon([spec("hang", "hang")])
    await wait_until(lambda: (tmp_path / "connectors" / "hang" / "pid").exists())
    pid = file_pid(tmp_path, "hang")
    hub.apply_soon([spec("a")])  # ждёт замка: после остановки не должен ничего запускать
    await hub.aclose()
    assert not alive(pid)
    assert hub.states() == []
    await hub.apply([spec("a")])
    hub.apply_soon([spec("a")])
    await asyncio.sleep(0.2)
    assert hub.states() == []
    assert not (tmp_path / "connectors" / "a" / "pid").exists()


async def test_bounded_aclose_kills_stubborn_connector(tmp_path: Path):
    hub = McpHub(tmp_path)
    await hub.start([spec("s", "stubborn"), spec("a")])
    pids = [file_pid(tmp_path, "s"), file_pid(tmp_path, "a")]
    assert state(hub, "s").state == "ready"
    began = time.monotonic()
    await hub.aclose(timeout_s=1.0)
    assert time.monotonic() - began < 2.5
    await wait_until(lambda: not any(alive(pid) for pid in pids), timeout=2.0)
    assert not (tmp_path / "run" / "connectors" / "s.pid").exists()
