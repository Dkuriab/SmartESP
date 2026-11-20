"""web_read через клиентскую сессию SDK в памяти; сеть — httpx.MockTransport."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp import Client

from tests.support import ARTICLE, HTML, Clock, Net, call, page, redirect, text_of
from web_mcp.server import build_server


async def test_read_page() -> None:
    net = Net({"https://example.com/cat": page(ARTICLE)})
    result = await call(net, "web_read", {"url": "https://example.com/cat"})
    assert not result.is_error
    assert text_of(result) == "Страница с сайта example.com: «Кошка».\n\nКошки любят спать."
    assert net.requests[0].headers["user-agent"]


async def test_read_plain_text() -> None:
    net = Net({"https://example.com/a.txt": page("строка 1\n\n  строка 2", {"content-type": "text/plain"})})
    result = await call(net, "web_read", {"url": "https://example.com/a.txt"})
    assert text_of(result) == "Страница с сайта example.com.\n\nстрока 1\nстрока 2"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///etc/passwd", "http и https"),
        ("ftp://example.com/x", "http и https"),
        ("http://localhost:8765/api/v1/status", "домашней сети"),
        ("http://192.168.1.1/", "домашней сети"),
        ("http://printer.local/", "домашней сети"),
        ("http://[::1]/", "домашней сети"),
    ],
)
async def test_read_refuses_bad_and_local_urls(url: str, expected: str) -> None:
    net = Net()
    result = await call(net, "web_read", {"url": url})
    assert result.is_error
    assert expected in text_of(result)
    assert net.requests == []


async def test_read_follows_redirects_relative_and_absolute() -> None:
    net = Net(
        {
            "http://example.com/old": redirect("https://example.com/new", 301),
            "https://example.com/new": redirect("/final"),
            "https://example.com/final": page(ARTICLE),
        }
    )
    result = await call(net, "web_read", {"url": "http://example.com/old"})
    assert not result.is_error
    assert "Кошки любят спать." in text_of(result)


async def test_read_redirect_to_local_address_is_refused() -> None:
    net = Net({"https://example.com/go": redirect("http://127.0.0.1:8765/api/v1/token")})
    result = await call(net, "web_read", {"url": "https://example.com/go"})
    assert result.is_error
    assert "домашней сети" in text_of(result)
    assert [str(r.url) for r in net.requests] == ["https://example.com/go"]


async def test_read_redirect_to_other_scheme_is_refused() -> None:
    net = Net({"https://example.com/go": redirect("file:///etc/passwd")})
    result = await call(net, "web_read", {"url": "https://example.com/go"})
    assert result.is_error
    assert "http и https" in text_of(result)


async def test_read_too_many_redirects() -> None:
    net = Net({f"https://example.com/{i}": redirect(f"https://example.com/{i + 1}") for i in range(5)})
    result = await call(net, "web_read", {"url": "https://example.com/0"})
    assert result.is_error
    assert "перенаправлений" in text_of(result)
    assert len(net.requests) == 4


async def test_read_refuses_binary_content() -> None:
    net = Net({"https://example.com/a.pdf": page("%PDF", {"content-type": "application/pdf"})})
    result = await call(net, "web_read", {"url": "https://example.com/a.pdf"})
    assert result.is_error
    assert "application/pdf" in text_of(result)


async def test_read_http_error_status() -> None:
    net = Net({"https://example.com/gone": page("нет", status=410)})
    result = await call(net, "web_read", {"url": "https://example.com/gone"})
    assert result.is_error
    assert "ошибкой 410" in text_of(result)


async def test_read_page_without_text() -> None:
    spa = "<html><body><div id='root'></div><script>render()</script></body></html>"
    net = Net({"https://example.com/app": page(spa)})
    result = await call(net, "web_read", {"url": "https://example.com/app"})
    assert result.is_error
    assert "без JavaScript" in text_of(result)


async def test_read_long_page_is_cut_to_limit() -> None:
    long_text = "".join(f"<p>Абзац номер {i}, в нём немного текста про кошек.</p>" for i in range(1000))
    net = Net({"https://example.com/long": page(f"<html><body>{long_text}</body></html>")})
    result = await call(net, "web_read", {"url": "https://example.com/long"})
    text = text_of(result)
    body = text.split("\n\n", 1)[1]
    assert body.endswith("(Дальше текст обрезан.)")
    assert len(body) <= 8000 + len("\n(Дальше текст обрезан.)") + 1


async def test_read_downloads_at_most_two_megabytes() -> None:
    sent: list[int] = []
    chunk = b"<p>" + "кот ".encode() * 16_000 + b"</p>"

    async def stream() -> AsyncIterator[bytes]:
        for _ in range(100):
            sent.append(len(chunk))
            yield chunk

    def huge(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=HTML, content=stream())

    net = Net({"https://example.com/huge": huge})
    result = await call(net, "web_read", {"url": "https://example.com/huge"})
    assert not result.is_error
    assert sum(sent) <= 2 * 1024 * 1024 + len(chunk)


async def test_read_timeout() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, text=ARTICLE, headers=HTML)

    server = build_server(httpx.MockTransport(handler), timeout=0.05)
    async with Client(server) as client:
        result = await client.call_tool("web_read", {"url": "https://example.com/slow"})
    assert result.is_error
    assert "не ответил" in text_of(result)


async def test_read_rate_limit() -> None:
    net = Net({"https://example.com/cat": page(ARTICLE)})
    async with Client(build_server(httpx.MockTransport(net), clock=Clock())) as client:
        results = [await client.call_tool("web_read", {"url": "https://example.com/cat"}) for _ in range(21)]
    assert not any(r.is_error for r in results[:20])
    assert "Слишком много запросов" in text_of(results[20])
