"""web_read не открывает домашнюю сеть: ссылка, перенаправления и адрес после DNS.

Сервер собран с настоящим GuardedBackend — подменены только DNS и сокеты.
"""

import pytest

from tests.support import ARTICLE, OWN_IP, PUBLIC_IP, Internet, call, page, redirect, text_of

LOCAL = "домашней сети"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///etc/passwd", "http и https"),
        ("ftp://example.com/x", "http и https"),
        ("http://localhost:8765/api/v1/status", LOCAL),
        ("http://192.168.1.1/", LOCAL),
        ("http://printer.local/", LOCAL),
        ("http://[::1]/", LOCAL),
    ],
)
async def test_refuses_bad_and_local_urls(url: str, expected: str) -> None:
    net = Internet()
    result = await call(net, "web_read", {"url": url})
    assert result.is_error
    assert expected in text_of(result)
    assert net.connected == []


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "::ffff:127.0.0.1", "169.254.169.254", "64:ff9b::7f00:1", OWN_IP, "192.168.68.115"],
)
async def test_refuses_name_resolving_to_home_network(address: str) -> None:
    net = Internet({"https://rebind.example/": page(ARTICLE)}, dns={"rebind.example": [address]})
    result = await call(net, "web_read", {"url": "https://rebind.example/"})
    assert result.is_error
    assert LOCAL in text_of(result)
    assert net.connected == []


async def test_connects_to_the_checked_address() -> None:
    net = Internet({"https://example.com/cat": page(ARTICLE)})
    result = await call(net, "web_read", {"url": "https://example.com/cat"})
    assert not result.is_error
    assert net.connected == [PUBLIC_IP]


async def test_redirect_to_local_address_is_refused() -> None:
    net = Internet({"https://example.com/go": redirect("http://127.0.0.1:8765/api/v1/token")})
    result = await call(net, "web_read", {"url": "https://example.com/go"})
    assert result.is_error
    assert LOCAL in text_of(result)
    assert [r.url for r in net.requests] == ["https://example.com/go"]


async def test_redirect_to_name_resolving_locally_is_refused() -> None:
    net = Internet(
        {"https://example.com/go": redirect("https://inside.example/admin")},
        dns={"inside.example": ["192.168.0.1"]},
    )
    result = await call(net, "web_read", {"url": "https://example.com/go"})
    assert result.is_error
    assert LOCAL in text_of(result)
    assert net.connected == [PUBLIC_IP]


async def test_redirect_to_other_scheme_is_refused() -> None:
    net = Internet({"https://example.com/go": redirect("file:///etc/passwd")})
    result = await call(net, "web_read", {"url": "https://example.com/go"})
    assert result.is_error
    assert "http и https" in text_of(result)
