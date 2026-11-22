"""Звуки с настоящим хабом и обновлениями: подключение колонки → лишний звук убран → итог от колонки."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from pathlib import Path

from fakes.fake_connection import FakeConnection
from smartesp.devices import DeviceHub
from smartesp.sounds import Sounds
from smartesp.updates import Updates


async def _decode(path: Path) -> AsyncGenerator[bytes]:
    yield path.read_bytes()


async def _eventually(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def test_connect_removes_stale_sound_and_reads_result(tmp_path: Path) -> None:
    hub = DeviceHub(0.3, 1.5, {})
    updates = Updates(tmp_path / "updates", hub.send_update)
    sounds = Sounds(tmp_path / "sounds", _decode, hub, updates.install)
    hub.add_connect_listener(sounds.device_connected)
    conn = FakeConnection("10.0.0.5:1")
    task = asyncio.create_task(hub.handle(conn))
    conn.feed_json("hello", fw="0.6.0", device_id="A", protocol=4, caps=["sounds"], sounds={"wake": "c" * 64})
    await _eventually(lambda: any(m["type"] == "update" for m in conn.sent_json()))
    assert conn.sent_json()[-1] == {"type": "update", "what": "sound", "tone": "wake", "size": 0}

    def wake_state() -> str:
        device = sounds.overview().devices[0]
        return next(t.delivery for t in device.tones if t.tone == "wake")

    assert wake_state() == "sending"
    conn.feed_json("update_status", what="sound", tone="wake", state="done", done=0, total=0, error="")
    await _eventually(lambda: wake_state() == "ok")
    await sounds.aclose()
    await hub.close_all()
    await hub.aclose()
    task.cancel()
