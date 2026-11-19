"""Общее для тестов хаба: описание тестового коннектора, ожидание условия."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from smartesp.tools import ConnectorSpec, ConnectorState, McpHub

SERVER = str(Path(__file__).with_name("mcp_test_server.py"))


def spec(cid: str, mode: str = "", enabled: bool = True, **env: str) -> ConnectorSpec:
    """Коннектор на тестовом сервере (запуск через sys.executable)."""
    args = (SERVER, mode) if mode else (SERVER,)
    return ConnectorSpec(
        id=cid, name=cid.upper(), command=sys.executable, args=args, env=env, enabled=enabled
    )


def state(hub: McpHub, cid: str) -> ConnectorState:
    """Состояние коннектора cid."""
    return next(s for s in hub.states() if s.id == cid)


async def wait_until(cond: Callable[[], bool], timeout: float = 10.0) -> None:
    """Ждёт, пока cond() станет истинным; иначе падает."""
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "условие не выполнилось вовремя"
        await asyncio.sleep(0.05)


async def tool_pid(hub: McpHub, name: str = "pid") -> int:
    """Номер процесса коннектора через его инструмент."""
    result = await hub.call(name, {}, None)
    assert not result.is_error, result.text
    return int(result.text)


def alive(pid: int) -> bool:
    """Жив ли процесс pid."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def file_pid(data_dir: Path, cid: str) -> int:
    """Номер процесса, который тестовый сервер записал в свою папку данных."""
    return int((data_dir / "connectors" / cid / "pid").read_text())
