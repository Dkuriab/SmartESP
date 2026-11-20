"""Защита от доступа к домашней сети: адреса, ссылки, подключение после DNS."""

import pytest

from web_mcp.guard import BadUrl, BlockedAddress, check_url, is_public_ip


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.5.6.7",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.10",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "::ffff:127.0.0.1",
        "::ffff:192.168.0.1",
        "ff02::1",
        "::7f00:1",
        "64:ff9b::a00:1",
        "2002:c0a8:101::1",
        "2001:0:4136:e378:8000:63bf:3f57:fefe",
        "fec0::1",
    ],
)
def test_private_addresses_are_not_public(address: str) -> None:
    assert not is_public_ip(address)


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "172.32.0.1", "93.184.216.34", "2a00:1450:4010::8a", "64:ff9b::808:808"],
)
def test_internet_addresses_are_public(address: str) -> None:
    assert is_public_ip(address)


def test_garbage_is_not_public() -> None:
    assert not is_public_ip("not-an-ip")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST:8080/admin",
        "http://api.localhost/",
        "http://printer.local/",
        "http://nas.home.arpa/",
        "http://router/",
        "http://127.0.0.1:8765/api/v1",
        "http://10.1.2.3/",
        "http://192.168.0.1/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_local_urls_are_blocked(url: str) -> None:
    with pytest.raises(BlockedAddress):
        check_url(url)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)", "example", ""]
)
def test_other_schemes_are_refused(url: str) -> None:
    with pytest.raises(BadUrl):
        check_url(url)


def test_public_url_passes() -> None:
    assert check_url("https://ru.wikipedia.org/wiki/Кот").host == "ru.wikipedia.org"
