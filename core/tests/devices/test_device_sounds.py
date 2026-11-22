"""Хаб и протокол: свои звуки — возможность sounds в hello, хэши, итог update звука."""

import asyncio
import json

from hub_helpers import LATE_S, WINDOW_S, FakeClock, eventually

from fakes.fake_connection import FakeConnection
from fakes.fake_events import RecordingSink
from smartesp.devices import DeviceHub, Hello, parse_message
from smartesp.devices.messages import UpdateStatus

SHA = "a" * 64


def test_hello_caps_and_sounds_parsed_and_garbage_skipped() -> None:
    text = json.dumps(
        {
            "type": "hello",
            "fw": "0.6.0",
            "device_id": "A",
            "protocol": 4,
            "caps": ["sounds", 5],
            "sounds": {"wake": SHA, "error": "zz", "thinking": 1},
        }
    )
    hello = parse_message(text)
    assert isinstance(hello, Hello)
    assert hello.caps == frozenset({"sounds"}) and hello.sounds == {"wake": SHA}
    old = parse_message(json.dumps({"type": "hello", "fw": "0.5.0", "device_id": "A", "protocol": 4}))
    assert isinstance(old, Hello) and old.caps == frozenset() and old.sounds == {}


def test_update_status_sound_has_tone() -> None:
    text = (
        '{"type":"update_status","what":"sound","tone":"wake","state":"done","done":2,"total":2,"error":""}'
    )
    assert parse_message(text) == UpdateStatus("sound", "done", 2, 2, "", "wake")


async def _connect(hub: DeviceHub, device_id: str, **hello: object) -> FakeConnection:
    conn = FakeConnection("10.0.0.9:1")
    asyncio.create_task(hub.handle(conn))  # noqa: RUF006 — живёт до конца теста
    conn.feed_json("hello", fw="0.6.0", device_id=device_id, protocol=4, **hello)
    await eventually(lambda: hub.supports_update(device_id))
    return conn


async def test_sound_only_to_capable_speaker_and_result_awaited() -> None:
    events = RecordingSink()
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock(), events=events)
    connected: list[str] = []
    hub.add_connect_listener(connected.append)
    old = await _connect(hub, "OLD")
    new = await _connect(hub, "NEW", caps=["sounds"], sounds={"attention": SHA})
    assert connected == ["OLD", "NEW"]
    assert hub.device_sounds("OLD") is None and hub.device_sounds("NEW") == {"attention": SHA}
    payload: dict[str, object] = {"what": "sound", "tone": "wake", "size": 0}
    assert not await hub.send_update("OLD", payload) and old.sent_json() == []
    result = hub.expect_sound("NEW", "wake")
    assert await hub.send_update("NEW", payload)
    assert new.sent_json()[-1] == {"type": "update", **payload}
    new.feed_json("update_status", what="sound", tone="wake", state="progress", done=1, total=2, error="")
    new.feed_json("update_status", what="sound", tone="wake", state="done", done=2, total=2, error="")
    progress = await asyncio.wait_for(result, 1.0)
    assert progress.state == "done"
    # звук — не «последнее обновление» колонки: панель прошивки о нём не говорит
    assert next(d for d in hub.devices() if d.device_id == "NEW").update is None
    assert not [data for kind, data in events.events if kind == "device_update"]
    await hub.close_all()
    await hub.aclose()
