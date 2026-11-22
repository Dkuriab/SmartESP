"""Хаб: обновление по воздуху — команда update только колонке с протоколом 4, ход из update_status."""

from hub_helpers import LATE_S, WINDOW_S, FakeClock, connect, eventually

from fakes.fake_events import RecordingSink
from smartesp.devices import DeviceHub


async def test_update_goes_only_to_protocol_4_and_progress_is_tracked() -> None:
    events = RecordingSink()
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock(), events=events)
    old, _ = await connect(hub, "OLD", protocol=3)
    conn, _ = await connect(hub, "NEW", protocol=4)
    await eventually(lambda: hub.supports_update("NEW"))
    payload: dict[str, object] = {"what": "model", "path": "/device/files/t", "size": 100, "sha256": "a" * 64}
    assert not hub.supports_update("OLD") and not await hub.send_update("OLD", payload)
    assert old.sent_json() == []
    assert await hub.send_update("NEW", payload)
    assert conn.sent_json()[-1] == {"type": "update", **payload}
    info = next(d for d in hub.devices() if d.device_id == "NEW")
    assert info.update is not None and (info.update.what, info.update.state, info.update.total) == (
        "model",
        "sent",
        100,
    )
    conn.feed_json("update_status", what="model", state="progress", done=40, total=100, error="")
    await eventually(lambda: next(d for d in hub.devices() if d.device_id == "NEW").update.done == 40)  # type: ignore[union-attr]
    conn.feed_json("update_status", what="model", state="failed", done=40, total=100, error="hash")
    await eventually(lambda: next(d for d in hub.devices() if d.device_id == "NEW").update.error == "hash")  # type: ignore[union-attr]
    kinds = [kind for kind, data in events.events if kind == "device_update" and data["device_id"] == "NEW"]
    assert len(kinds) == 3
    conn.feed_json("update_status", what="rom", state="done", done=1, total=1)  # мусор — мимо
    assert next(d for d in hub.devices() if d.device_id == "NEW").update.error == "hash"  # type: ignore[union-attr]
