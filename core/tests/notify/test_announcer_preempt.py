"""Тесты очереди объявлений: занятая колонка — без синтеза, вытеснение файла объявлением."""

import asyncio
from collections.abc import AsyncIterator

from announcer_helpers import RETRY_S, finished, texts, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.contracts import Preempt
from smartesp.notify import Announcer


class Speaker:
    """Синтез-подделка со счётчиком вызовов."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, text: str) -> AsyncIterator[bytes]:
        self.calls += 1
        yield text.encode()


def setup(preempt: Preempt | None = None) -> tuple[FakeDevicePort, RecordingSink, Speaker, Announcer]:
    port = FakeDevicePort({"kitchen": "Кухня"})
    port.proactive = {"kitchen"}
    sink, speak = RecordingSink(), Speaker()
    announcer = Announcer(port, speak, events=sink, retry_s=RETRY_S, preempt=preempt)
    return port, sink, speak, announcer


async def test_busy_speaker_is_not_synthesized() -> None:
    port, sink, speak, announcer = setup()
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер.", "timer")
    await asyncio.sleep(RETRY_S * 10)
    assert speak.calls == 0 and port.announces == []  # повторы без синтеза
    port.busy = set()
    await until(lambda: bool(finished(sink)))
    assert speak.calls == 1
    assert texts(port) == ["Таймер."]
    await announcer.aclose()


async def test_announcement_preempts_file() -> None:
    stopped: list[str] = []

    async def preempt(device_id: str) -> bool:
        stopped.append(device_id)
        port.busy.discard(device_id)  # файл остановлен — колонка свободна
        return True

    port, sink, speak, announcer = setup(preempt)
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер.", "timer")
    await until(lambda: bool(finished(sink)))
    assert stopped == ["kitchen"]
    assert texts(port) == ["Таймер."] and speak.calls == 1
    assert finished(sink)[0]["status"] == "ok"
    await announcer.aclose()


async def test_nothing_to_preempt_waits() -> None:
    calls: list[str] = []

    async def preempt(device_id: str) -> bool:
        calls.append(device_id)
        return False  # идёт разговор, а не файл

    port, sink, speak, announcer = setup(preempt)
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер.", "timer")
    await until(lambda: len(calls) >= 3)
    assert speak.calls == 0 and port.announces == []
    port.busy = set()
    await until(lambda: bool(finished(sink)))
    assert texts(port) == ["Таймер."]
    await announcer.aclose()


async def test_failing_preempt_is_treated_as_busy() -> None:
    async def preempt(device_id: str) -> bool:
        raise RuntimeError("сломалось")

    port, sink, speak, announcer = setup(preempt)
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер.", "timer")
    await asyncio.sleep(RETRY_S * 5)
    assert speak.calls == 0
    port.busy = set()
    await until(lambda: bool(finished(sink)))
    await announcer.aclose()
