"""Защита от доступа к домашней сети: адреса, ссылки, подключение после DNS."""

from collections.abc import Iterable

import httpcore
import httpx
import pytest

from web_mcp.guard import BlockedAddress, GuardedBackend, check_url, is_public_ip, make_guarded_transport


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
    ],
)
def test_private_addresses_are_not_public(address: str) -> None:
    assert not is_public_ip(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "172.32.0.1", "93.184.216.34", "2a00:1450:4010::8a"])
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
    with pytest.raises(ValueError):
        check_url(url)


def test_public_url_passes() -> None:
    assert check_url("https://ru.wikipedia.org/wiki/Кот").host == "ru.wikipedia.org"


class FakeStream(httpcore.AsyncNetworkStream):
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None


class FakeInner(httpcore.AsyncNetworkBackend):
    def __init__(self, refuse: Iterable[str] = ()) -> None:
        self.connected: list[tuple[str, int]] = []
        self.refuse = set(refuse)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected.append((host, port))
        if host in self.refuse:
            raise httpcore.ConnectError("refused")
        return FakeStream()

    async def sleep(self, seconds: float) -> None:
        return None


def resolver(table: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return table[host]

    return resolve


async def test_backend_connects_to_checked_address() -> None:
    inner = FakeInner()
    backend = GuardedBackend(resolver({"example.com": ["93.184.216.34"]}), inner)
    await backend.connect_tcp("example.com", 443)
    assert inner.connected == [("93.184.216.34", 443)]


async def test_backend_refuses_host_resolving_to_home_network() -> None:
    inner = FakeInner()
    backend = GuardedBackend(resolver({"evil.example": ["192.168.1.1"]}), inner)
    with pytest.raises(BlockedAddress):
        await backend.connect_tcp("evil.example", 80)
    assert inner.connected == []


async def test_backend_refuses_when_any_address_is_private() -> None:
    inner = FakeInner()
    backend = GuardedBackend(resolver({"mixed.example": ["93.184.216.34", "127.0.0.1"]}), inner)
    with pytest.raises(BlockedAddress):
        await backend.connect_tcp("mixed.example", 80)
    assert inner.connected == []


async def test_backend_tries_next_address_when_first_fails() -> None:
    inner = FakeInner(refuse=["93.184.216.34"])
    backend = GuardedBackend(resolver({"example.com": ["93.184.216.34", "93.184.216.35"]}), inner)
    await backend.connect_tcp("example.com", 80)
    assert [host for host, _ in inner.connected] == ["93.184.216.34", "93.184.216.35"]


async def test_backend_without_addresses_fails_to_connect() -> None:
    backend = GuardedBackend(resolver({"empty.example": []}), FakeInner())
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("empty.example", 80)


async def test_block_passes_through_httpx_client() -> None:
    """Отказ из сетевого слоя доходит до вызывающего как BlockedAddress, а не как сетевая ошибка."""
    inner = FakeInner()
    transport = make_guarded_transport(resolver({"rebind.example": ["10.0.0.5"]}), inner)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddress):
            await client.get("http://rebind.example/")
    assert inner.connected == []
