"""Общее для тестов инструментов: поддельный интернет за настоящим защищённым сетевым слоем.

Internet — поддельные DNS и сетевой слой httpcore (внутренний для GuardedBackend):
«сайты» отвечают сырыми байтами HTTP/1.1 по адресу запроса. Сервер собирается с
настоящими GuardedBackend, httpcore и распаковкой — подменены только DNS и сокеты.
"""

import asyncio
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

import httpcore
from mcp import Client
from mcp.types import CallToolResult, TextContent

from web_mcp.server import build_server

ARTICLE = (
    "<html><head><title>Кошка</title></head><body><nav>Меню</nav><p>Кошки любят спать.</p></body></html>"
)
HTML = {"content-type": "text/html; charset=utf-8"}
PUBLIC_IP = "93.184.216.34"
# «глобальный IPv6 самого компьютера» для тестов
OWN_IP = "2a02:6b8:0:1::5"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@dataclass(frozen=True)
class Seen:
    """Запрос, каким его увидел «сайт»."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Answer:
    status: int = 200
    headers: dict[str, str] = field(default_factory=lambda: dict(HTML))
    body: bytes | Iterable[bytes] = b""
    delay: float = 0.0


Handler = Callable[[Seen], Answer]


def page(body: str, headers: dict[str, str] | None = None, status: int = 200) -> Handler:
    return lambda _: Answer(status, dict(HTML) if headers is None else headers, body.encode())


def redirect(location: str, status: int = 302) -> Handler:
    return lambda _: Answer(status, {"location": location})


def _wire(answer: Answer) -> Iterator[bytes]:
    lines = [
        f"HTTP/1.1 {answer.status} X",
        *(f"{k}: {v}" for k, v in answer.headers.items()),
        "Connection: close",
    ]
    if isinstance(answer.body, bytes):
        lines.append(f"Content-Length: {len(answer.body)}")
    yield ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    yield from [answer.body] if isinstance(answer.body, bytes) else answer.body


class FakeStream(httpcore.AsyncNetworkStream):
    """Соединение с «сайтом»: копит запрос, затем отдаёт ответ кусками."""

    def __init__(self, net: "Internet") -> None:
        self._net = net
        self._tls = False
        self._raw = b""
        self._out: Iterator[bytes] | None = None
        self._buffer = b""
        self._delay = 0.0

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._raw += buffer
        head, sep, body = self._raw.partition(b"\r\n\r\n")
        if not sep or self._out is not None:
            return
        first, *rest = head.decode("latin-1").split("\r\n")
        headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in rest)}
        if len(body) < int(headers.get("content-length", "0")):
            return
        method, target, _ = first.split(" ", 2)
        url = f"{'https' if self._tls else 'http'}://{headers['host']}{target}"
        answer = self._net.answer(Seen(method, url, headers, body))
        self._delay = answer.delay
        self._out = _wire(answer)

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
            self._delay = 0.0
        if not self._buffer and self._out is not None:
            self._buffer = next(self._out, b"")
        piece, self._buffer = self._buffer[:max_bytes], self._buffer[max_bytes:]
        return piece

    async def start_tls(
        self, ssl_context: object, server_hostname: str | None = None, timeout: float | None = None
    ) -> httpcore.AsyncNetworkStream:
        self._tls = True
        return self

    async def aclose(self) -> None:
        return None

    def get_extra_info(self, info: str) -> object:
        return None


class Internet(httpcore.AsyncNetworkBackend):
    """Поддельные DNS (по умолчанию — публичный адрес) и сайты по полному адресу."""

    def __init__(
        self, routes: dict[str, Handler] | None = None, dns: dict[str, list[str]] | None = None
    ) -> None:
        self.routes = routes or {}
        self.dns = dns or {}
        self.requests: list[Seen] = []
        self.connected: list[str] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        return self.dns.get(host, [PUBLIC_IP])

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected.append(host)
        return FakeStream(self)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def answer(self, seen: Seen) -> Answer:
        self.requests.append(seen)
        handler = self.routes.get(seen.url)
        return handler(seen) if handler is not None else Answer(404, body=b"")


def server_for(net: Internet, clock: Callable[[], float] | None = None, timeout: float = 8.0):
    """Сервер с настоящей защитой; подменены только DNS, сокеты и адреса компьютера."""
    return build_server(
        resolve=net.resolve,
        backend=net,
        own_addresses=lambda: [OWN_IP, "192.168.68.115"],
        clock=clock or Clock(),
        timeout=timeout,
    )


def text_of(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(net: Internet, name: str, args: dict[str, object]) -> CallToolResult:
    """Один вызов инструмента на свежем сервере."""
    async with Client(server_for(net)) as client:
        return await client.call_tool(name, args)
