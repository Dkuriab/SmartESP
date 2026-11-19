"""Общие фикстуры: сервер заметок в памяти и клиент SDK."""

from datetime import datetime
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import RequestParamsMeta

from notes_mcp.server import build_server

NOW = datetime(2026, 11, 19, 10, 32)


class Caller:
    """Вызов инструмента через клиент-сессию SDK в памяти; возвращает текст ответа.

    Сессия открывается на каждый вызов: фикстура с async with ломает отмену задач anyio.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def __call__(
        self, name: str, arguments: dict[str, object] | None = None, person: str | None = None
    ) -> str:
        meta = RequestParamsMeta(person=person) if person is not None else None
        async with Client(self._server) as client:
            result = await client.call_tool(name, arguments or {}, meta=meta)
        assert not result.is_error, result
        return "".join(getattr(c, "text", "") for c in result.content)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def call(data_dir: Path) -> Caller:
    return Caller(build_server(data_dir, now=lambda: NOW))
