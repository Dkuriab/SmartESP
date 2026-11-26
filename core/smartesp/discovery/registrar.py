"""Настоящий регистратор: служба `_smartesp._tcp` через python-zeroconf (async)."""

from __future__ import annotations

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from smartesp.contracts import DEVICE_PATH, SERVICE_TYPE, ServiceRecord


def service_info(record: ServiceRecord) -> AsyncServiceInfo:
    """Описание службы: имя и хост `smartesp-<id>`, TXT id/path/version, адреса из записи."""
    name = f"smartesp-{record.core_id}"
    return AsyncServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        port=record.port,
        properties={"id": record.core_id, "path": DEVICE_PATH, "version": record.version},
        server=f"{name}.local.",
        parsed_addresses=list(record.addresses),
    )


class ZeroconfRegistrar:
    """Одна публикация: свой AsyncZeroconf на адресах записи (только IPv4)."""

    def __init__(self) -> None:
        self._zeroconf: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    async def register(self, record: ServiceRecord) -> None:
        """Публикует службу; занятое имя — zeroconf подберёт другое (id в TXT не меняется)."""
        self._zeroconf = AsyncZeroconf(interfaces=list(record.addresses), ip_version=IPVersion.V4Only)
        info = service_info(record)
        await (await self._zeroconf.async_register_service(info, allow_name_change=True))
        self._info = info

    async def aclose(self) -> None:
        """Снимает службу (прощальная рассылка) и закрывает сокеты."""
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = self._info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                await (await zeroconf.async_unregister_service(info))
        finally:
            await zeroconf.async_close()
