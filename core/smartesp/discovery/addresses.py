"""IPv4-адреса Mac, по которым колонки могут достучаться до ядра."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

import ifaddr


def pick_addresses(ips: Iterable[str]) -> tuple[str, ...]:
    """Годные для объявления адреса по порядку: только IPv4, без loopback и 169.254.x.x, без повторов.

    Адресов может быть несколько (Wi-Fi, кабель, VPN): колонка сама берёт тот, что в её подсети.
    """
    picked: list[str] = []
    for ip in ips:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        usable = address.version == 4 and not address.is_loopback and not address.is_link_local
        if usable and ip not in picked:
            picked.append(ip)
    return tuple(picked)


def local_ipv4() -> tuple[str, ...]:
    """Адреса сетевых интерфейсов Mac сейчас (ifaddr, без сетевых запросов)."""
    ips = (str(ip.ip) for adapter in ifaddr.get_adapters() for ip in adapter.ips if ip.is_IPv4)
    return pick_addresses(ips)
