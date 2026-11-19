"""Описание коннектора из настроек и его состояние для интерфейса."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

StateName = Literal["starting", "ready", "failed", "disabled"]

# on_announce(text, person, connector_id): коннектор просит что-то сказать вслух
AnnounceHandler = Callable[[str, str | None, str], None]


@dataclass(frozen=True)
class ConnectorSpec:
    """Коннектор из настроек: как его запустить.

    id — короткое имя (папка данных, префикс инструментов при совпадении имён);
    name — имя для людей («Таймеры»); command и args — команда запуска (stdio);
    env — дополнительные переменные окружения; enabled — включён ли.
    """

    id: str
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict[str, str])
    enabled: bool = True


@dataclass(frozen=True)
class ConnectorState:
    """Состояние коннектора для интерфейса.

    tools — имена инструментов, как их видит модель (только у готового);
    error — текст последней ошибки (пусто, если её нет).
    """

    id: str
    name: str
    state: StateName
    tools: tuple[str, ...] = ()
    error: str = ""
