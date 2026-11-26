"""Объявление ядра в сети: постоянный id, выбор адресов, публикация и её обновление (без сети)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from fakes.fake_registrar import FakeRegistrars
from smartesp.contracts import ServiceRecord
from smartesp.discovery import Advertiser, load_or_create_core_id, pick_addresses, service_info


def test_core_id_is_created_once_and_kept(tmp_path: Path) -> None:
    first = load_or_create_core_id(tmp_path)
    assert len(first) == 12 and int(first, 16) >= 0
    assert load_or_create_core_id(tmp_path) == first
    assert (tmp_path / "core_id").read_text(encoding="utf-8").strip() == first


def test_broken_core_id_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "core_id").write_text("не hex\n", encoding="utf-8")
    fresh = load_or_create_core_id(tmp_path)
    assert len(fresh) == 12 and fresh != "не hex"


def test_pick_addresses_drops_loopback_link_local_ipv6_and_repeats() -> None:
    ips = ["127.0.0.1", "192.168.1.10", "169.254.3.4", "fe80::1", "192.168.1.10", "10.0.0.5", "bad"]
    assert pick_addresses(ips) == ("192.168.1.10", "10.0.0.5")


def test_service_info_carries_type_port_and_txt() -> None:
    info = service_info(ServiceRecord("a1b2c3d4e5f6", 8765, "0.1.0", ("192.168.1.10",)))
    assert info.type == "_smartesp._tcp.local."
    assert info.name == "smartesp-a1b2c3d4e5f6._smartesp._tcp.local."
    assert info.server == "smartesp-a1b2c3d4e5f6.local."
    assert info.port == 8765
    assert info.properties == {b"id": b"a1b2c3d4e5f6", b"path": b"/device", b"version": b"0.1.0"}
    assert info.parsed_addresses() == ["192.168.1.10"]


class Addresses:
    """Подделка адресов Mac: меняется в тесте."""

    def __init__(self, *ips: str) -> None:
        self.ips: tuple[str, ...] = ips

    def __call__(self) -> tuple[str, ...]:
        return self.ips


def advertiser(registrars: FakeRegistrars, addresses: Addresses) -> Advertiser:
    return Advertiser(registrars, lambda ips: ServiceRecord("id1", 8765, "v", ips), addresses, check_s=3600)


async def test_publishes_and_withdraws_on_close() -> None:
    registrars = FakeRegistrars()
    adv = advertiser(registrars, Addresses("192.168.1.10"))
    await adv.refresh()
    assert registrars.published() == [ServiceRecord("id1", 8765, "v", ("192.168.1.10",))]
    await adv.refresh()  # адреса те же — повторно не публикуется
    assert len(registrars.made) == 1
    await adv.aclose()
    assert registrars.published() == []


async def test_republishes_when_mac_address_changes() -> None:
    registrars = FakeRegistrars()
    addresses = Addresses("192.168.1.10")
    adv = advertiser(registrars, addresses)
    await adv.refresh()
    addresses.ips = ("192.168.1.42",)
    await adv.refresh()
    assert registrars.published() == [ServiceRecord("id1", 8765, "v", ("192.168.1.42",))]
    assert [action for action, _ in registrars.log] == ["register", "close", "register"]


async def test_no_network_publishes_nothing_until_it_appears() -> None:
    registrars = FakeRegistrars()
    addresses = Addresses()
    adv = advertiser(registrars, addresses)
    await adv.refresh()
    assert registrars.made == []
    addresses.ips = ("10.0.0.5",)
    await adv.refresh()
    assert [r.addresses for r in registrars.published()] == [("10.0.0.5",)]


async def test_failure_is_logged_and_retried(caplog: pytest.LogCaptureFixture) -> None:
    registrars = FakeRegistrars()
    registrars.fail = True
    adv = advertiser(registrars, Addresses("192.168.1.10"))
    with caplog.at_level(logging.WARNING):
        await adv.refresh()
    assert "не удалось объявить" in caplog.text
    assert registrars.published() == []
    registrars.fail = False
    await adv.refresh()  # следующая проверка пробует снова
    assert len(registrars.published()) == 1


async def test_start_runs_in_background_and_close_stops_it() -> None:
    registrars = FakeRegistrars()
    adv = Advertiser(
        registrars, lambda ips: ServiceRecord("id1", 1, "v", ips), Addresses("10.0.0.5"), check_s=0.01
    )
    adv.start()
    async with asyncio.timeout(2):
        while not registrars.published():
            await asyncio.sleep(0.005)
    await adv.aclose()
    assert registrars.published() == []
    await adv.aclose()  # повторно — без ошибок
