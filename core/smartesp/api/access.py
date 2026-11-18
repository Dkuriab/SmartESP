"""Адреса Mac в локальной сети: по ним интерфейс открывают с других компьютеров."""

from __future__ import annotations

import socket

_PROBE_ADDRESS = ("10.255.255.255", 1)


def _hostname_addresses() -> list[str]:
    """IPv4-адреса, которые разрешает имя этого компьютера."""
    infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    return [str(info[4][0]) for info in infos]


def _outbound_address() -> list[str]:
    """Адрес исходящего интерфейса: UDP-«соединение» ничего не отправляет."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(_PROBE_ADDRESS)
        return [str(sock.getsockname()[0])]


def lan_addresses() -> list[str]:
    """IPv4-адреса Mac без `127.*` и повторов; сбой источника даёт пропуск источника."""
    found: list[str] = []
    for source in (_hostname_addresses, _outbound_address):
        try:
            found.extend(source())
        except OSError:
            continue
    return [ip for ip in dict.fromkeys(found) if not ip.startswith("127.")]
