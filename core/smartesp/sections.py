"""Связка: разделы настроек, применяемые на лету (аналог wiring.py для правок config).

Каждый раздел — Section(build, swap, release): собрать новое из настроек, подменить живое,
освободить старое. Логики здесь нет, только соединение частей.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from smartesp.config import Config, SpeechConfig
from smartesp.contracts import Section
from smartesp.conversation import History, Orchestrator
from smartesp.devices import DeviceHub
from smartesp.kinds import connector_specs
from smartesp.lifecycle import Answering, LiveAnswering
from smartesp.notify import Announcer
from smartesp.tools import ConnectorSpec, McpHub


class BuildAnswering(Protocol):
    """Сборка живой пары по настройкам; warm=False — без прогрева тех же моделей (пересборка)."""

    def __call__(self, config: Config, *, warm: bool = True) -> Awaitable[Answering]: ...


async def _devices(config: Config) -> tuple[dict[str, str], dict[str, int]]:
    """Имена (пустое — не задано: колонка подписана MAC) и громкость колонок из настроек."""
    names = {device_id: device.name for device_id, device in config.devices.items() if device.name}
    return names, {device_id: device.volume for device_id, device in config.devices.items()}


def _apply_devices(hub: DeviceHub, value: object) -> None:
    names, volumes = cast(tuple[dict[str, str], dict[str, int]], value)
    hub.set_names(names)
    hub.set_volumes(volumes)


async def _history_limits(config: Config) -> tuple[int, int]:
    return config.history.max_turns, config.history.max_age_s


async def _speech(config: Config) -> SpeechConfig:
    return config.speech


async def _connectors(config: Config) -> list[ConnectorSpec]:
    return connector_specs(config)


def speech_settings(orchestrator: Orchestrator, announcer: Announcer) -> Callable[[SpeechConfig], None]:
    """Раздел speech для живых частей: оркестратор (запоздавшие ответы, вопрос) и очередь речи."""

    def use(speech: SpeechConfig) -> None:
        orchestrator.set_speech(speech.proactive, speech.listen_after_question)
        announcer.set_listen_after(speech.listen_after_question)

    return use


def live_sections(
    hub: DeviceHub,
    history: History,
    live: LiveAnswering,
    build_answering: BuildAnswering,
    use_speech: Callable[[SpeechConfig], None],
    tools: McpHub,
) -> dict[str, Section]:
    """Разделы, применяемые на лету (tts пульт открывает через менеджер голосов).

    connectors хаб применяет в фоне; сеть с новыми инструментами пересобирается, когда
    коннекторы встанут (ToolsRefresh в wiring.py) — без прогрева: модели те же, а
    выгруженную владельцем модель пересборка обратно не грузит.
    """
    cold = functools.partial(build_answering, warm=False)
    answering = Section(build_answering, live.use, live.release, refresh=cold)
    return {
        "devices": Section(_devices, functools.partial(_apply_devices, hub)),
        "history": Section(_history_limits, lambda new: history.set_limits(*cast(tuple[int, int], new))),
        "executors": answering,
        "stages": answering,  # правила обработчиков в промптах: пересобираем и сеть
        "cloud": answering,  # ключ облачного сервиса: исполнители kind cloud собираются заново
        "speech": Section(_speech, lambda speech: use_speech(cast(SpeechConfig, speech))),
        "connectors": Section(_connectors, lambda specs: tools.apply_soon(cast(list[ConnectorSpec], specs))),
    }
