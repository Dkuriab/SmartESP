from __future__ import annotations

import socket
from typing import Any

import pytest

from smartesp.api.access import lan_addresses


def _infos(*ips: str) -> list[Any]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]


class _Sock:
    def __init__(self, ip: str | None) -> None:
        self.ip = ip

    def __enter__(self) -> _Sock:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def connect(self, _: object) -> None:
        if self.ip is None:
            raise OSError("no route")

    def getsockname(self) -> tuple[str, int]:
        return (self.ip or "", 0)


def test_merges_dedupes_and_drops_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("127.0.0.1", "10.0.0.5", "10.0.0.5"))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _Sock("192.168.1.7"))
    assert lan_addresses() == ["10.0.0.5", "192.168.1.7"]


def test_os_errors_skip_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object, **__: object) -> list[Any]:
        raise OSError("dns")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _Sock(None))
    assert lan_addresses() == []


def test_drops_unspecified_and_link_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("0.0.0.0", "169.254.10.1", "10.0.0.5"))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _Sock("169.254.3.3"))
    assert lan_addresses() == ["10.0.0.5"]
