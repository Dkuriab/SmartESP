"""Описание коннектора из настроек (состояние для интерфейса — в contracts)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from smartesp.contracts import ConnectorKind, ConnectorStateName

StateName = ConnectorStateName

# on_announce(text, person, connector_id): коннектор просит что-то сказать вслух
AnnounceHandler = Callable[[str, str | None, str], None]


@dataclass(frozen=True)
class ConnectorSpec:
    """Коннектор из настроек: как его запустить.

    id — короткое имя (папка данных, префикс инструментов при совпадении имён);
    name — имя для людей («Таймеры»); command и args — команда запуска (stdio);
    env — дополнительные переменные окружения; enabled — включён ли; kind — коннектор (MCP) или
    клиент ядра (обычная программа, см. client.py); core_api — коннектору нужны адрес и токен API
    ядра (флаг smartesp.json; клиент получает их всегда).
    """

    id: str
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict[str, str])
    enabled: bool = True
    kind: ConnectorKind = "mcp"
    core_api: bool = False  # передать адрес и токен API ядра (объявлено в smartesp.json коннектора)
