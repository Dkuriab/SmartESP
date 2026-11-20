"""web_search через клиентскую сессию SDK в памяти; интернет — подделка (tests/support.py)."""

import gzip
import os
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from mcp import Client

from tests.support import Answer, Clock, Internet, Seen, call, page, server_for, text_of
from web_mcp.server import build_server

DDG = (Path(__file__).parent / "fixtures" / "ddg_results.html").read_text(encoding="utf-8")


async def test_tools_listed_in_russian() -> None:
    async with Client(server_for(Internet())) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {"web_search", "web_read"}
    for tool in tools:
        assert tool.description
        assert any("а" <= ch.lower() <= "я" for ch in tool.description)


async def test_search_posts_to_duckduckgo_in_russian_region() -> None:
    net = Internet({"https://html.duckduckgo.com/html/": page(DDG)})
    result = await call(net, "web_search", {"query": "курс доллара"})
    assert not result.is_error
    request = net.requests[0]
    assert request.method == "POST"
    form = parse_qs(request.body.decode())
    assert form == {"q": ["курс доллара"], "kl": ["ru-ru"]}
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.headers["accept-encoding"] == "gzip, deflate"
    # порядок как у httpx: с другим DuckDuckGo через раз отвечал капчей
    assert list(request.headers) == [
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "content-length",
        "content-type",
    ]
    assert request.headers["user-agent"].startswith("SmartEsp-web/")
    text = text_of(result)
    assert "cbr.ru: Центральный банк" in text
    assert "https://www.banki.ru/products/currency/usd/" in text
    assert result.structured_content is not None
    results = result.structured_content["results"]
    assert len(results) == 5
    assert set(results[0]) == {"title", "url", "snippet"}


async def test_search_nothing_found() -> None:
    net = Internet(
        {"https://html.duckduckgo.com/html/": page("<html><body><div id='links'></div></body></html>")}
    )
    result = await call(net, "web_search", {"query": "абракадабра"})
    assert not result.is_error
    assert text_of(result) == "Ничего не нашлось по запросу «абракадабра»."


async def test_search_empty_query() -> None:
    net = Internet()
    result = await call(net, "web_search", {"query": "   "})
    assert result.is_error
    assert "что искать" in text_of(result)
    assert net.requests == []


async def test_search_captcha_is_honest_and_pauses() -> None:
    captcha = '<form id="challenge-form" action="//duckduckgo.com/anomaly.js"></form>'
    net = Internet({"https://html.duckduckgo.com/html/": page(captcha, status=202)})
    clock = Clock()
    async with Client(server_for(net, clock)) as client:
        first = await client.call_tool("web_search", {"query": "новости"})
        second = await client.call_tool("web_search", {"query": "новости"})
        assert len(net.requests) == 1
        clock.now += 301
        await client.call_tool("web_search", {"query": "новости"})
    assert first.is_error and second.is_error
    assert "Поиск сейчас недоступен" in text_of(first)
    assert "Поиск сейчас недоступен" in text_of(second)
    assert len(net.requests) == 2


async def test_search_network_failure() -> None:
    # имя поисковика не разрешается — как без сети
    net = Internet(dns={"html.duckduckgo.com": []})
    result = await call(net, "web_search", {"query": "новости"})
    assert result.is_error
    assert "Поиск сейчас недоступен" in text_of(result)


async def test_search_rate_limit() -> None:
    net = Internet({"https://html.duckduckgo.com/html/": page(DDG)})
    clock = Clock()
    async with Client(server_for(net, clock)) as client:
        results = [await client.call_tool("web_search", {"query": f"q{i}"}) for i in range(11)]
        clock.now += 61
        later = await client.call_tool("web_search", {"query": "ещё"})
    assert not any(r.is_error for r in results[:10])
    assert results[10].is_error
    assert "Слишком много запросов" in text_of(results[10])
    assert len(net.requests) == 11
    assert not later.is_error


async def test_search_reads_gzip_reply() -> None:
    def packed(_: Seen) -> Answer:
        return Answer(
            headers={"content-type": "text/html", "content-encoding": "gzip"},
            body=gzip.compress(DDG.encode()),
        )

    result = await call(
        Internet({"https://html.duckduckgo.com/html/": packed}), "web_search", {"query": "кот"}
    )
    assert not result.is_error
    assert "cbr.ru:" in text_of(result)


@pytest.mark.skipif(not os.environ.get("WEB_LIVE"), reason="WEB_LIVE не задан")
async def test_live_search_and_read() -> None:
    async with Client(build_server()) as client:
        found = await client.call_tool("web_search", {"query": "Википедия кошка"})
        assert not found.is_error, text_of(found)
        read = await client.call_tool("web_read", {"url": "https://ru.wikipedia.org/wiki/Кошка"})
        assert not read.is_error, text_of(read)
        # localtest.me в публичном DNS указывает на 127.0.0.1 — отказ после разрешения имени
        local = await client.call_tool("web_read", {"url": "http://localtest.me/"})
        assert local.is_error
        assert "домашней сети" in text_of(local)
