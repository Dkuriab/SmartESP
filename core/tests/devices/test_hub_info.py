"""Тесты хаба: сведения о колонках, имена на лету, события, остановка."""

import asyncio

from hub_helpers import LATE_S, WINDOW_S, FakeClock, accepted_turn, connect, eventually

from fakes.fake_events import RecordingSink
from smartesp.devices import DeviceHub


class Wall:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(names: dict[str, str] | None = None) -> tuple[DeviceHub, FakeClock, Wall, RecordingSink]:
    clock, wall, sink = FakeClock(), Wall(), RecordingSink()
    hub = DeviceHub(WINDOW_S, LATE_S, names or {}, clock=clock, events=sink, wall_clock=wall)
    return hub, clock, wall, sink


async def test_connected_device_info() -> None:
    hub, _, wall, _ = make({"A": "Кухня"})
    conn, _task = await connect(hub, "A", remote="10.0.0.9:1")
    await eventually(lambda: bool(hub.devices()) and hub.devices()[0].connected)
    info = hub.devices()[0]
    assert (info.name, info.fw, info.remote, info.last_seen) == ("Кухня", "2.0", "10.0.0.9:1", 1000.0)
    wall.now = 1005.0
    conn.feed(bytes(2))
    await eventually(lambda: hub.devices()[0].last_seen == 1005.0)


async def test_disconnected_keeps_info() -> None:
    hub, _, _, _ = make()
    conn, task = await connect(hub, "A")
    await eventually(lambda: hub.devices()[0].connected if hub.devices() else False)
    conn.fail()
    await task
    info = hub.devices()[0]
    assert not info.connected and info.fw == "2.0" and info.last_seen == 1000.0


async def test_configured_never_seen_and_sorting() -> None:
    hub, _, _, _ = make({"A": "Ярко", "B": "Балкон"})
    infos = hub.devices()
    assert [i.device_id for i in infos] == ["B", "A"]
    assert all(not i.connected and i.fw == "" and i.remote == "" and i.last_seen is None for i in infos)


async def test_set_names_live() -> None:
    hub, _, _, _ = make({"A": "Кухня"})
    hub.set_names({"A": "Спальня", "C": "Зал"})
    assert hub.device_name("A") == "Спальня"
    assert [i.name for i in hub.devices()] == ["Зал", "Спальня"]


async def test_connection_and_wake_events() -> None:
    hub, clock, _, sink = make({"A": "Кухня"})
    conn, task = await accepted_turn(hub, clock, "A")
    assert sink.events[0] == (
        "device_connected",
        {"device_id": "A", "name": "Кухня", "remote": "10.0.0.7:5000", "fw": "2.0"},
    )
    assert ("wake", {"device_id": "A", "level": -30.0}) in sink.events
    assert ("arbitration", {"device_id": "A", "decision": "accept"}) in sink.events
    conn.fail()
    await task
    assert sink.events[-1] == ("device_disconnected", {"device_id": "A"})


async def test_arbitration_cancel_event() -> None:
    hub, clock, _, sink = make()
    a, _ = await connect(hub, "A")
    b, _ = await connect(hub, "B")
    a.feed_json("wake", turn=1, level=-20.0)
    b.feed_json("wake", turn=1, level=-40.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: ("arbitration", {"device_id": "B", "decision": "cancel"}) in sink.events)
    assert ("arbitration", {"device_id": "A", "decision": "accept"}) in sink.events


async def test_stop_accepting_cancels_wake() -> None:
    hub, _, _, _ = make()
    conn, _ = await connect(hub, "A")
    await eventually(lambda: bool(hub.devices()))
    hub.stop_accepting()
    conn.feed_json("wake", turn=5, level=-30.0)
    conn.feed(bytes(1024))
    conn.feed_json("utterance_end", turn=5, reason="vad")
    await eventually(lambda: any(m.get("type") == "cancel_turn" for m in conn.sent_json()))
    assert [m for m in conn.sent_json() if m["type"] == "cancel_turn"][0]["turn"] == 5
    try:
        await asyncio.wait_for(hub.next_utterance(), 0.1)
        raise AssertionError("utterance queued")
    except TimeoutError:
        pass


async def test_close_all_closes_every_connection() -> None:
    hub, _, _, _ = make()
    a, ta = await connect(hub, "A")
    b, tb = await connect(hub, "B")
    await eventually(lambda: len(hub.devices()) == 2 and all(i.connected for i in hub.devices()))
    await hub.close_all()
    assert a.closed and b.closed
    await asyncio.gather(ta, tb)
