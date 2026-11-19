"""Связка: разделы настроек, применяемые на лету (аналог wiring.py для правок config).

Каждый раздел — Section(build, swap, release): собрать новое из настроек, подменить живое,
освободить старое. Логики здесь нет, только соединение частей.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from smartesp.config import Config
from smartesp.contracts import Section
from smartesp.conversation import History
from smartesp.devices import DeviceHub
from smartesp.lifecycle import Answering, LiveAnswering


async def _device_names(config: Config) -> dict[str, str]:
    return {device_id: device.name for device_id, device in config.devices.items()}


async def _history_limits(config: Config) -> tuple[int, int]:
    return config.history.max_turns, config.history.max_age_s


def live_sections(
    hub: DeviceHub,
    history: History,
    live: LiveAnswering,
    build_answering: Callable[[Config], Awaitable[Answering]],
) -> dict[str, Section]:
    """Разделы, применяемые на лету (tts пульт открывает через менеджер голосов)."""
    answering = Section(build_answering, live.use, live.release)
    return {
        "devices": Section(_device_names, lambda names: hub.set_names(cast(dict[str, str], names))),
        "history": Section(_history_limits, lambda new: history.set_limits(*cast(tuple[int, int], new))),
        "executors": answering,
        "stages": answering,  # правила обработчиков в промптах: пересобираем и сеть
    }
