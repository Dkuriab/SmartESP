"""Защита домашней сети: web_read открывает только адреса интернета.

Две ступени. check_url — до запроса и на каждом перенаправлении: схема http/https,
имя не локальное (localhost, .local, без точки), IP в ссылке — не частный.
GuardedBackend — при каждом подключении: имя разрешается через DNS, все адреса
проверяются, подключение идёт к проверенному адресу. Так подмена DNS между
проверкой и подключением (DNS rebinding) ничего не даёт.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import cast

import httpcore
import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]

_LOCAL_SUFFIXES = (".localhost", ".local", ".home.arpa", ".internal", ".lan")


class BadUrl(ValueError):
    """Ссылка не http/https или без адреса сайта."""


class BlockedAddress(Exception):
    """Адрес ведёт в домашнюю сеть или на сам компьютер."""


def is_public_ip(text: str) -> bool:
    """True — адрес из интернета; частные, локальные, служебные и мусор — False."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def check_url(url: str) -> httpx.URL:
    """Проверяет ссылку; плохая схема — BadUrl, локальный адрес — BlockedAddress."""
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as error:
        raise BadUrl(str(error)) from error
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise BadUrl(f"unsupported url: {url}")
    host = parsed.host.lower().rstrip(".")
    if _is_ip(host):
        if not is_public_ip(host):
            raise BlockedAddress(host)
        return parsed
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        raise BlockedAddress(host)
    return parsed


async def system_resolve(host: str, port: int) -> list[str]:
    """Адреса имени через системный DNS (без повторов, в порядке ответа)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise httpcore.ConnectError(f"cannot resolve {host}: {error}") from error
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Сетевой слой httpcore: разрешает имя, проверяет адреса и подключается к ним."""

    def __init__(self, resolve: Resolver, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._resolve = resolve
        # в __init__ httpcore AnyIOBackend объявлен через try/except, pyright видит заглушку
        default = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())
        self._inner: httpcore.AsyncNetworkBackend = inner or default

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
        for address in addresses:
            if not is_public_ip(address):
                raise BlockedAddress(f"{host} -> {address}")
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


def make_guarded_transport(
    resolve: Resolver | None = None, inner: httpcore.AsyncNetworkBackend | None = None
) -> httpx.AsyncHTTPTransport:
    """Транспорт httpx, который подключается только к адресам интернета.

    Клиент с ним создаётся с trust_env=False: через прокси из окружения адрес
    разрешал бы прокси, и проверка не работала бы.
    """
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    # httpx 0.28 не даёт задать сетевой слой снаружи — подменяем пул (версия зафиксирована)
    transport._pool = httpcore.AsyncConnectionPool(  # pyright: ignore[reportPrivateUsage]
        ssl_context=httpx.create_ssl_context(trust_env=False),
        network_backend=GuardedBackend(resolve or system_resolve, inner),
    )
    return transport
