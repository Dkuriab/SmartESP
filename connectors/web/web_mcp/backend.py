"""Защита домашней сети, вторая ступень: проверка адреса при каждом подключении.

GuardedBackend — сетевой слой httpcore: сам разрешает имя через DNS, отказывает,
если хоть один адрес не из интернета или принадлежит самому компьютеру, и
подключается к проверенному адресу. Так подмена DNS между проверкой и
подключением (DNS rebinding) ничего не даёт. Внешний IPv4 роутера так не узнать
(нужен запрос наружу) — он не запрещается.
"""

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import cast

import httpcore
import psutil

from web_mcp.guard import BlockedAddress, IPAddress, is_public_ip, parse_ip

Resolver = Callable[[str, int], Awaitable[list[str]]]
AddressProvider = Callable[[], Iterable[str]]

OWN_REFRESH_SECONDS = 60.0

log = logging.getLogger("web_mcp")


async def system_resolve(host: str, port: int) -> list[str]:
    """Адреса имени через системный DNS (без повторов, в порядке ответа)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise httpcore.ConnectError(f"cannot resolve {host}: {error}") from error
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def interface_addresses() -> list[str]:
    """Все IPv4/IPv6 адреса сетевых интерфейсов компьютера (включая глобальные IPv6)."""
    families = (socket.AF_INET, socket.AF_INET6)
    return [
        item.address for items in psutil.net_if_addrs().values() for item in items if item.family in families
    ]


def _normalise(address: IPAddress) -> IPAddress:
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped if mapped is not None else address


class OwnAddresses:
    """Адреса самого компьютера; список обновляется не чаще раза в минуту."""

    def __init__(
        self,
        provider: AddressProvider = interface_addresses,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._addresses: set[IPAddress] = set()
        self._loaded_at: float | None = None

    def _refresh(self) -> None:
        now = self._clock()
        if self._loaded_at is not None and now - self._loaded_at < OWN_REFRESH_SECONDS:
            return
        self._loaded_at = now
        try:
            parsed = (parse_ip(text) for text in self._provider())
            self._addresses = {_normalise(address) for address in parsed if address is not None}
        except Exception:
            log.exception("cannot list interface addresses")

    def __contains__(self, text: object) -> bool:
        address = parse_ip(text) if isinstance(text, str) else None
        if address is None:
            return False
        self._refresh()
        return _normalise(address) in self._addresses


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Сетевой слой httpcore: разрешает имя, проверяет адреса и подключается к ним."""

    def __init__(
        self,
        resolve: Resolver = system_resolve,
        inner: httpcore.AsyncNetworkBackend | None = None,
        own: OwnAddresses | None = None,
    ) -> None:
        self._resolve = resolve
        # в __init__ httpcore AnyIOBackend объявлен через try/except, pyright видит заглушку
        default = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())
        self._inner: httpcore.AsyncNetworkBackend = inner or default
        self._own = own or OwnAddresses()

    def _check(self, host: str, addresses: list[str]) -> None:
        for address in addresses:
            if not is_public_ip(address) or address in self._own:
                raise BlockedAddress(f"{host} -> {address}")

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await self._resolve(host, port)
        if not addresses:
            raise httpcore.ConnectError(f"no addresses for {host}")
        self._check(host, addresses)
        error: Exception = httpcore.ConnectError(f"cannot connect to {host}")
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as failure:
                error = failure
        raise error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedAddress("unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
