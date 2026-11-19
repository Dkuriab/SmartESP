"""Тесты очереди объявлений: сбои синтеза речи — повторы с пределом, без сигнала на колонке."""

import asyncio
from collections.abc import AsyncIterator

from announcer_helpers import RETRY_S, finished, speak, texts, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.contracts import Delivery
from smartesp.notify import Announcer
from smartesp.notify.announcer import MAX_SYNTH_FAILURES


async def test_speech_failure_is_retried() -> None:
    port = FakeDevicePort()
    port.proactive = {"kitchen"}
    sink = RecordingSink()
    calls: list[str] = []

    def flaky(text: str) -> AsyncIterator[bytes]:
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("синтез речи не готов")
        return speak(text)

    announcer = Announcer(port, flaky, events=sink, retry_s=RETRY_S)
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    assert len(calls) == 2 and texts(port) == ["Готово."]
    assert finished(sink)[0]["status"] == "ok"
    await announcer.aclose()


async def test_synthesis_fails_at_start() -> None:
    port = FakeDevicePort()
    port.proactive = {"kitchen"}
    sink = RecordingSink()
    calls: list[str] = []

    async def broken(text: str) -> AsyncIterator[bytes]:
        calls.append(text)
        raise RuntimeError("синтез упал")
        yield b""  # pragma: no cover — генератор

    announcer = Announcer(port, broken, events=sink, retry_s=RETRY_S)
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    assert len(calls) == 1 + MAX_SYNTH_FAILURES  # первая попытка и два повтора
    assert port.announces == [] and port.tones == []  # колонка ничего не получила: нет и attention
    assert finished(sink)[0]["status"] == "undelivered"
    await asyncio.sleep(RETRY_S * 3)
    assert len(calls) == 1 + MAX_SYNTH_FAILURES
    await announcer.aclose()


async def test_synthesis_fails_mid_stream() -> None:
    port = FakeDevicePort()
    port.proactive = {"kitchen"}
    sink = RecordingSink()

    async def breaks(text: str) -> AsyncIterator[bytes]:
        yield b"first"
        raise RuntimeError("синтез упал")

    announcer = Announcer(port, breaks, events=sink, retry_s=RETRY_S)
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    assert [(call.audio, call.result) for call in port.announces] == [(b"first", "lost")] * 3
    assert finished(sink)[0]["status"] == "undelivered"
    await asyncio.sleep(RETRY_S * 3)
    assert len(port.announces) == 1 + MAX_SYNTH_FAILURES  # не каждые retry_s до срока
    await announcer.aclose()


async def test_busy_closes_synthesis() -> None:
    port = FakeDevicePort()
    port.proactive = {"kitchen"}
    sink = RecordingSink()
    closed: list[str] = []
    streams: list[AsyncIterator[bytes]] = []  # держим ссылки: закрыть должен Announcer, а не сборщик мусора

    async def stream(text: str) -> AsyncIterator[bytes]:
        try:
            yield b"first"
            yield b"rest"
        finally:
            closed.append(text)

    def tracked(text: str) -> AsyncIterator[bytes]:
        streams.append(stream(text))
        return streams[-1]

    async def busy(device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        return "busy"  # колонка занята: звук не взят

    port.announce = busy
    announcer = Announcer(port, tracked, events=sink, retry_s=RETRY_S)
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: len(closed) >= 2)  # каждая попытка закрывает свой поток синтеза
    await announcer.aclose()
