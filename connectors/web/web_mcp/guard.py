"""Защита домашней сети, первая ступень: проверка ссылки и IP-адреса.

check_url — до запроса и на каждом перенаправлении: схема http/https, имя не
локальное (localhost, .local, без точки), IP в ссылке — не частный. Вторая
ступень — при подключении, после DNS (см. backend.GuardedBackend).
"""

import ipaddress

import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

_LOCAL_SUFFIXES = (".localhost", ".local", ".home.arpa", ".internal", ".lan")


class BadUrl(ValueError):
    """Ссылка не http/https или без адреса сайта."""


class BlockedAddress(Exception):
    """Адрес ведёт в домашнюю сеть или на сам компьютер."""


def parse_ip(text: str) -> IPAddress | None:
    """IP-адрес из строки (зона «%en0» отбрасывается); не адрес — None."""
    try:
        return ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None


def _embedded_ipv4(address: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 внутри IPv6: ::ffff:a.b.c.d, ::a.b.c.d, NAT64, 6to4, Teredo."""
    found: list[ipaddress.IPv4Address] = []
    if address.ipv4_mapped is not None:
        found.append(address.ipv4_mapped)
    if int(address) >> 32 == 0 or address in _NAT64:
        found.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    if address.sixtofour is not None:
        found.append(address.sixtofour)
    if address.teredo is not None:
        found.extend(address.teredo)
    return found


def _is_global(address: IPAddress) -> bool:
    return address.is_global and not address.is_multicast


def is_public_ip(text: str) -> bool:
    """True — адрес из интернета; частные, локальные, служебные и мусор — False.

    Для IPv6 со встроенным IPv4 (NAT64, 6to4, Teredo, mapped) проверяется и он.
    """
    address = parse_ip(text)
    if address is None or not _is_global(address):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local:
            return False
        return all(_is_global(inner) for inner in _embedded_ipv4(address))
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
    if parse_ip(host) is not None:
        if not is_public_ip(host):
            raise BlockedAddress(host)
        return parsed
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        raise BlockedAddress(host)
    return parsed
