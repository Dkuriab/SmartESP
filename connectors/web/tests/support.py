"""Общее для тестов инструментов: поддельная сеть, часы, вызов через сессию SDK в памяти."""

from collections.abc import Callable

import httpx
from mcp import Client
from mcp.types import CallToolResult, TextContent

from web_mcp.server import build_server

ARTICLE = (
    "<html><head><title>Кошка</title></head><body><nav>Меню</nav><p>Кошки любят спать.</p></body></html>"
)
HTML = {"content-type": "text/html; charset=utf-8"}

Handler = Callable[[httpx.Request], httpx.Response]


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Net:
    """Поддельная сеть: запоминает запросы, отвечает по адресу."""

    def __init__(self, routes: dict[str, Handler] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(str(request.url))
        if handler is None:
            return httpx.Response(404)
        return handler(request)


def page(body: str, headers: dict[str, str] | None = None, status: int = 200) -> Handler:
    return lambda _: httpx.Response(status, text=body, headers=HTML if headers is None else headers)


def redirect(location: str, status: int = 302) -> Handler:
    return lambda _: httpx.Response(status, headers={"location": location})


def text_of(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(net: Net, name: str, args: dict[str, object]) -> CallToolResult:
    """Один вызов инструмента на свежем сервере."""
    async with Client(build_server(httpx.MockTransport(net))) as client:
        return await client.call_tool(name, args)
