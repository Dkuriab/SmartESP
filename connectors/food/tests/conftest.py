"""Общие фикстуры: сервер питания в памяти, поддельный Open Food Facts и клиент SDK."""

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import RequestParamsMeta

from food_mcp.server import build_server

NOW = datetime(2026, 11, 19, 10, 32)

# Настоящие контрольные суммы: EAN-13 и EAN-8.
BARCODE = "4607001771562"
BARCODE_8 = "40170725"


class FakeOff:
    """Поддельный Open Food Facts: ответы по штрихкоду, «нет сети», журнал запросов."""

    def __init__(self) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.offline = False
        self.timeout = False
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("нет сети", request=request)
        if self.timeout:
            raise httpx.ReadTimeout("долго", request=request)
        code = request.url.path.rsplit("/", 1)[-1]
        product = self.products.get(code)
        if product is None:
            return httpx.Response(404, json={"status": 0, "status_verbose": "product not found"})
        return httpx.Response(200, json={"status": 1, "code": code, "product": product})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


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


class Clock:
    """Часы, которые тест может перевести."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def off() -> FakeOff:
    return FakeOff()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def call(data_dir: Path, off: FakeOff, clock: Clock) -> Caller:
    return Caller(build_server(data_dir, now=clock, transport=off.transport()))
