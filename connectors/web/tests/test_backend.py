"""Сетевой слой с проверкой адресов после DNS и адреса самого компьютера."""

import httpcore
import pytest

from tests.support import Clock
from web_mcp.backend import GuardedBackend, OwnAddresses
from web_mcp.guard import BlockedAddress


class FakeStream(httpcore.AsyncNetworkStream):
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None


class FakeInner(httpcore.AsyncNetworkBackend):
    def __init__(self, refuse: tuple[str, ...] = ()) -> None:
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


def backend(table: dict[str, list[str]], inner: FakeInner, own: tuple[str, ...] = ()) -> GuardedBackend:
    return GuardedBackend(resolver(table), inner, OwnAddresses(lambda: own))


async def test_connects_to_checked_address() -> None:
    inner = FakeInner()
    await backend({"example.com": ["93.184.216.34"]}, inner).connect_tcp("example.com", 443)
    assert inner.connected == [("93.184.216.34", 443)]


@pytest.mark.parametrize("address", ["192.168.1.1", "10.0.0.5", "::ffff:127.0.0.1", "64:ff9b::a00:1"])
async def test_refuses_host_resolving_to_home_network(address: str) -> None:
    inner = FakeInner()
    with pytest.raises(BlockedAddress):
        await backend({"evil.example": [address]}, inner).connect_tcp("evil.example", 80)
    assert inner.connected == []


async def test_refuses_when_any_address_is_private() -> None:
    inner = FakeInner()
    with pytest.raises(BlockedAddress):
        await backend({"mixed.example": ["93.184.216.34", "127.0.0.1"]}, inner).connect_tcp(
            "mixed.example", 80
        )
    assert inner.connected == []


async def test_refuses_own_global_ipv6_of_this_computer() -> None:
    inner = FakeInner()
    own = ("2601:4c2:4300:46d0::2a56",)
    guarded = backend({"me.example": ["2601:4c2:4300:46d0:0::2a56"]}, inner, own)
    with pytest.raises(BlockedAddress):
        await guarded.connect_tcp("me.example", 80)
    assert inner.connected == []


async def test_tries_next_address_when_first_fails() -> None:
    inner = FakeInner(refuse=("93.184.216.34",))
    guarded = backend({"example.com": ["93.184.216.34", "93.184.216.35"]}, inner)
    await guarded.connect_tcp("example.com", 80)
    assert [host for host, _ in inner.connected] == ["93.184.216.34", "93.184.216.35"]


async def test_without_addresses_fails_to_connect() -> None:
    with pytest.raises(httpcore.ConnectError):
        await backend({"empty.example": []}, FakeInner()).connect_tcp("empty.example", 80)


async def test_unix_sockets_are_refused() -> None:
    with pytest.raises(BlockedAddress):
        await backend({}, FakeInner()).connect_unix_socket("/var/run/docker.sock")


def test_own_addresses_refresh_at_most_once_a_minute() -> None:
    calls: list[int] = []
    current = ["2a00::1"]

    def provider() -> list[str]:
        calls.append(1)
        return list(current)

    clock = Clock()
    own = OwnAddresses(provider, clock)
    assert "2a00::1" in own
    current[:] = ["2a00::2"]
    clock.now += 30
    assert "2a00::2" not in own
    clock.now += 31
    assert "2a00::2" in own
    assert "2a00::1" not in own
    assert len(calls) == 2


def test_own_addresses_normalise_scope_and_mapping() -> None:
    own = OwnAddresses(lambda: ["fe80::1%en0", "203.0.113.7", "garbage"])
    assert "fe80::1" in own
    assert "::ffff:203.0.113.7" in own
    assert "203.0.113.8" not in own


def test_own_addresses_survive_provider_failure() -> None:
    def broken() -> list[str]:
        raise OSError("no interfaces")

    assert "203.0.113.7" not in OwnAddresses(broken)
