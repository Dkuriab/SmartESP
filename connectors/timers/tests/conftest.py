"""Общие заготовки тестов: поддельные часы, папка данных, клиент в памяти."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import LoggingMessageNotificationParams, RequestParamsMeta, TextContent

from tests.fake_clock import FakeClock
from timers_mcp.server import build_server

# Местное время тестов: UTC+3, 19 ноября 2026, 14:00.
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 11, 19, 14, 0, tzinfo=TZ)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


class Session:
    """Клиент в памяти и полученные им объявления."""

    def __init__(self, client: Client, inbox: MemoryObjectReceiveStream[dict[str, Any]]) -> None:
        self.client = client
        self._inbox = inbox

    async def call(self, tool: str, person: str | None = None, **args: Any) -> str:
        """Вызывает инструмент и возвращает текст ответа."""
        meta = RequestParamsMeta(person=person) if person is not None else None
        result = await self.client.call_tool(tool, args, meta=meta)
        block = result.content[0]
        assert isinstance(block, TextContent)
        return block.text

    async def announce(self) -> dict[str, Any]:
        """Ждёт следующее объявление (предел — защита от зависания, не ожидание времени)."""
        with anyio.fail_after(5):
            return await self._inbox.receive()

    def pending(self) -> list[dict[str, Any]]:
        """Объявления, уже пришедшие и ещё не прочитанные."""
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self._inbox.receive_nowait())
            except anyio.WouldBlock:
                return items


@asynccontextmanager
async def connect(server: MCPServer[Any]) -> AsyncGenerator[Session]:
    """Подключает клиента в памяти (рукопожатие, как по stdio) и ловит уведомления журнала."""
    send, receive = anyio.create_memory_object_stream[dict[str, Any]](100)

    async def on_log(params: LoggingMessageNotificationParams) -> None:
        if params.logger == "smartesp":
            await send.send(params.data)

    async with send, receive, Client(server, mode="legacy", logging_callback=on_log) as client:
        yield Session(client, receive)


ServerFactory = Callable[[], MCPServer[Any]]


@pytest.fixture
def make_server(clock: FakeClock, data_dir: Path) -> ServerFactory:
    """Фабрика сервера: каждый вызов — «новый запуск» с той же папкой данных."""

    def make() -> MCPServer[Any]:
        return build_server(data_dir, clock)

    return make
