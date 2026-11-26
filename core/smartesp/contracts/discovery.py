"""Договор: объявление ядра в локальной сети (Bonjour/mDNS), чтобы колонки нашли его сами."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SERVICE_TYPE = "_smartesp._tcp.local."  # служба ядра; колонка ищет «_smartesp», «_tcp»
DEVICE_PATH = "/device"  # путь WebSocket колонок (TXT path)


@dataclass(frozen=True)
class ServiceRecord:
    """Что объявить: постоянный id ядра (TXT id), порт сервера, версия ядра (TXT version)
    и IPv4-адреса Mac, по которым ядро доступно."""

    core_id: str
    port: int
    version: str
    addresses: tuple[str, ...]


class Registrar(Protocol):
    """Регистратор службы в сети: один объект — одна публикация."""

    async def register(self, record: ServiceRecord) -> None:
        """Публикует службу; ошибка (нет сети, занято имя) — исключение."""
        ...

    async def aclose(self) -> None:
        """Снимает публикацию и освобождает сеть. Безопасно вызывать после неудачной register."""
        ...
