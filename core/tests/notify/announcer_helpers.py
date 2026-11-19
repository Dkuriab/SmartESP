"""Помощники тестов очереди объявлений: подделки колонок и событий, ожидание итога."""

import asyncio
from collections.abc import AsyncIterator, Callable

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.notify import Announcer

RETRY_S = 0.01


async def speak(text: str) -> AsyncIterator[bytes]:
    """Синтез-подделка: весь текст одним куском."""
    yield text.encode()


def setup(
    *proactive: str, retry_s: float = RETRY_S, expire_s: float = 600.0
) -> tuple[FakeDevicePort, RecordingSink, Announcer]:
    """Колонки v3 proactive, приёмник событий и очередь с быстрыми повторами."""
    port = FakeDevicePort({"kitchen": "Кухня", "hall": "Прихожая"})
    port.proactive = set(proactive)
    sink = RecordingSink()
    return port, sink, Announcer(port, speak, events=sink, retry_s=retry_s, expire_s=expire_s)


def finished(sink: RecordingSink) -> list[dict[str, object]]:
    """Данные событий turn_finished по порядку."""
    return [data for kind, data in sink.events if kind == "turn_finished"]


async def until(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.002)


def texts(port: FakeDevicePort) -> list[str]:
    return [call.audio.decode() for call in port.announces]
