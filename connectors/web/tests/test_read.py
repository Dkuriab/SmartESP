"""web_read через клиентскую сессию SDK в памяти; интернет — подделка (tests/support.py)."""

import gzip
import zlib
from collections.abc import Iterator

from mcp import Client

from tests.support import (
    ARTICLE,
    HTML,
    Answer,
    Clock,
    Internet,
    Seen,
    call,
    page,
    redirect,
    server_for,
    text_of,
)


async def test_read_page() -> None:
    net = Internet({"https://example.com/cat": page(ARTICLE)})
    result = await call(net, "web_read", {"url": "https://example.com/cat"})
    assert not result.is_error
    assert text_of(result) == "Страница с сайта example.com: «Кошка».\n\nКошки любят спать."
    assert net.requests[0].headers["user-agent"]


async def test_read_plain_text() -> None:
    net = Internet(
        {"https://example.com/a.txt": page("строка 1\n\n  строка 2", {"content-type": "text/plain"})}
    )
    result = await call(net, "web_read", {"url": "https://example.com/a.txt"})
    assert text_of(result) == "Страница с сайта example.com.\n\nстрока 1\nстрока 2"


async def test_read_follows_redirects_relative_and_absolute() -> None:
    net = Internet(
        {
            "http://example.com/old": redirect("https://example.com/new", 301),
            "https://example.com/new": redirect("/final"),
            "https://example.com/final": page(ARTICLE),
        }
    )
    result = await call(net, "web_read", {"url": "http://example.com/old"})
    assert not result.is_error
    assert "Кошки любят спать." in text_of(result)


async def test_read_too_many_redirects() -> None:
    net = Internet({f"https://example.com/{i}": redirect(f"https://example.com/{i + 1}") for i in range(5)})
    result = await call(net, "web_read", {"url": "https://example.com/0"})
    assert result.is_error
    assert "перенаправлений" in text_of(result)
    assert len(net.requests) == 4


async def test_read_refuses_binary_content() -> None:
    net = Internet({"https://example.com/a.pdf": page("%PDF", {"content-type": "application/pdf"})})
    result = await call(net, "web_read", {"url": "https://example.com/a.pdf"})
    assert result.is_error
    assert "application/pdf" in text_of(result)


async def test_read_http_error_status() -> None:
    net = Internet({"https://example.com/gone": page("нет", status=410)})
    result = await call(net, "web_read", {"url": "https://example.com/gone"})
    assert result.is_error
    assert "ошибкой 410" in text_of(result)


async def test_read_page_without_text() -> None:
    spa = "<html><body><div id='root'></div><script>render()</script></body></html>"
    net = Internet({"https://example.com/app": page(spa)})
    result = await call(net, "web_read", {"url": "https://example.com/app"})
    assert result.is_error
    assert "без JavaScript" in text_of(result)


async def test_read_long_page_is_cut_to_limit() -> None:
    long_text = "".join(f"<p>Абзац номер {i}, в нём немного текста про кошек.</p>" for i in range(1000))
    net = Internet({"https://example.com/long": page(f"<html><body>{long_text}</body></html>")})
    result = await call(net, "web_read", {"url": "https://example.com/long"})
    text = text_of(result)
    body = text.split("\n\n", 1)[1]
    assert body.endswith("(Дальше текст обрезан.)")
    assert len(body) <= 8000 + len("\n(Дальше текст обрезан.)") + 1


async def test_read_downloads_at_most_two_megabytes() -> None:
    sent: list[int] = []
    chunk = b"<p>" + "кот ".encode() * 16_000 + b"</p>"

    def stream() -> Iterator[bytes]:
        for _ in range(100):
            sent.append(len(chunk))
            yield chunk

    def huge(_: Seen) -> Answer:
        return Answer(body=stream())

    net = Internet({"https://example.com/huge": huge})
    result = await call(net, "web_read", {"url": "https://example.com/huge"})
    assert not result.is_error
    assert sum(sent) <= 2 * 1024 * 1024 + len(chunk)


async def test_read_timeout() -> None:
    net = Internet({"https://example.com/slow": lambda _: Answer(body=ARTICLE.encode(), delay=5)})
    async with Client(server_for(net, timeout=0.05)) as client:
        result = await client.call_tool("web_read", {"url": "https://example.com/slow"})
    assert result.is_error
    assert "не ответил" in text_of(result)


async def test_read_rate_limit() -> None:
    net = Internet({"https://example.com/cat": page(ARTICLE)})
    async with Client(server_for(net, Clock())) as client:
        # отказы проверки ссылки предел не тратят
        for _ in range(25):
            await client.call_tool("web_read", {"url": "http://localhost/"})
        results = [await client.call_tool("web_read", {"url": "https://example.com/cat"}) for _ in range(21)]
    assert not any(r.is_error for r in results[:20])
    assert "Слишком много запросов" in text_of(results[20])


def gzipped(body: bytes | list[bytes], encoding: str = "gzip") -> Answer:
    return Answer(headers={**HTML, "content-encoding": encoding}, body=body)


async def test_read_gzip_page() -> None:
    net = Internet({"https://example.com/cat": lambda _: gzipped(gzip.compress(ARTICLE.encode()))})
    result = await call(net, "web_read", {"url": "https://example.com/cat"})
    assert not result.is_error
    assert text_of(result).endswith("Кошки любят спать.")
    assert net.requests[0].headers["accept-encoding"] == "gzip, deflate"


async def test_read_stacked_gzip_is_refused() -> None:
    twice = gzip.compress(gzip.compress(ARTICLE.encode()))
    net = Internet({"https://example.com/cat": lambda _: gzipped(twice, "gzip, gzip")})
    result = await call(net, "web_read", {"url": "https://example.com/cat"})
    assert result.is_error
    assert "сжат" in text_of(result)


async def test_read_gzip_bomb_is_cut() -> None:
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"<p>kot</p>" * 100_000  # 1 МБ
    bomb = b"".join(packer.compress(block) for _ in range(50)) + packer.flush()
    parts = [bomb[i : i + 65536] for i in range(0, len(bomb), 65536)]
    net = Internet({"https://example.com/bomb": lambda _: gzipped(parts)})
    result = await call(net, "web_read", {"url": "https://example.com/bomb"})
    assert not result.is_error
    assert text_of(result).endswith("(Дальше текст обрезан.)")
