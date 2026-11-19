"""Файл на настоящем хабе с поддельной колонкой: кадры хода ядра, остановка и перебивание."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from pathlib import Path

import pytest

from fakes.fake_connection import FakeConnection
from fakes.fake_events import RecordingSink
from smartesp.contracts import PlaybackRefused
from smartesp.devices import DeviceHub
from smartesp.fileplay import FilePlayer
from smartesp.notify import Announcer

T1 = 0x80000001  # первый ход ядра в сессии колонки
ANNOUNCE_T1 = '{"type":"announce","turn":2147483649}'
CANCEL_T1 = '{"type":"cancel_turn","turn":2147483649}'
FIRST = b"\x01" * 100


async def eventually(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


class Endless:
    """Разбор файла: первый кусок сразу, дальше — ничего, пока не закроют (длинный файл)."""

    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def __call__(self, path: Path) -> AsyncGenerator[bytes]:
        try:
            yield FIRST
            await asyncio.Event().wait()
            yield b""
        finally:
            self.closed.set()


async def upload() -> AsyncGenerator[bytes]:
    yield b"file"


@pytest.fixture
async def hub() -> AsyncGenerator[DeviceHub]:
    hub = DeviceHub(0.3, 1.5, {})
    yield hub
    await hub.aclose()


async def speaker(hub: DeviceHub, device_id: str, protocol: int) -> FakeConnection:
    conn = FakeConnection()
    asyncio.create_task(hub.handle(conn))
    conn.feed_json("hello", fw="2.0", device_id=device_id, protocol=protocol)
    await eventually(lambda: any(d.device_id == device_id and d.connected for d in hub.devices()))
    return conn


def finished(events: RecordingSink) -> list[object]:
    return [data["delivery"] for kind, data in events.events if kind == "playback_finished"]


async def test_stop_sends_cancel_turn(hub: DeviceHub, tmp_path: Path) -> None:
    conn = await speaker(hub, "A", 3)
    events, decode = RecordingSink(), Endless()
    player = FilePlayer(hub, hub.devices, decode, events=events, tmp_dir=tmp_path)
    await player.play_file("A", upload())
    await eventually(lambda: FIRST in conn.sent)
    assert conn.sent[0] == ANNOUNCE_T1
    assert await player.stop_file("A") is True
    await eventually(lambda: CANCEL_T1 in conn.sent)
    assert finished(events) == ["interrupted"]
    assert decode.closed.is_set()
    assert list(tmp_path.iterdir()) == []


async def test_wake_word_interrupts(hub: DeviceHub, tmp_path: Path) -> None:
    conn = await speaker(hub, "A", 3)
    events = RecordingSink()
    player = FilePlayer(hub, hub.devices, Endless(), events=events, tmp_dir=tmp_path)
    await player.play_file("A", upload())
    conn.feed_json("barge_in", turn=T1)
    await eventually(lambda: finished(events) == ["interrupted"])
    await player.play_file("A", upload())  # колонка снова свободна
    await player.aclose()


async def test_v2_speaker_refused(hub: DeviceHub, tmp_path: Path) -> None:
    conn = await speaker(hub, "B", 2)
    player = FilePlayer(hub, hub.devices, Endless(), events=RecordingSink(), tmp_dir=tmp_path)
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("B", upload())
    assert refused.value.reason == "unsupported"
    assert ANNOUNCE_T1 not in conn.sent


async def test_announcement_preempts_file(hub: DeviceHub, tmp_path: Path) -> None:
    conn = await speaker(hub, "A", 3)
    events, decode = RecordingSink(), Endless()
    player = FilePlayer(hub, hub.devices, decode, events=events, tmp_dir=tmp_path)
    spoken: list[str] = []

    async def speak(text: str) -> AsyncGenerator[bytes]:
        spoken.append(text)
        yield b"\x05" * 100

    announcer = Announcer(hub, speak, events=events, retry_s=0.01, preempt=player.stop_file)
    await player.play_file("A", upload())
    announcer.say("A", "Таймер.", "timer")
    await eventually(lambda: b"\x05" * 100 in conn.sent)
    assert finished(events) == ["interrupted"]  # файл прерван объявлением и не возобновится
    assert CANCEL_T1 in conn.sent
    assert conn.sent.index(CANCEL_T1) < conn.sent.index('{"type":"announce","turn":2147483650}')
    assert spoken == ["Таймер."]
    assert decode.closed.is_set() and list(tmp_path.iterdir()) == []
    await announcer.aclose()
