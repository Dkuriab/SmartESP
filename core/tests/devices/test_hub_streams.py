"""Хаб: потоки звука (протокол 5) — команды stream_* только колонке v5, отчёты и отключение — слушателю."""

from hub_helpers import LATE_S, WINDOW_S, FakeClock, connect, eventually

from smartesp.contracts import StreamCommand, StreamReport
from smartesp.devices import DeviceHub, parse_message


async def test_commands_go_only_to_protocol_5() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock())
    old, _ = await connect(hub, "OLD", protocol=4)
    new, _ = await connect(hub, "NEW", protocol=5)
    await eventually(lambda: hub.supports_stream("NEW"))
    start = StreamCommand("start", 7, "/device/stream/t", 16000, 0.5, live=True)
    assert not hub.supports_stream("OLD") and not await hub.send_stream("OLD", start)
    assert old.sent_json() == []
    assert await hub.send_stream("NEW", start)
    assert await hub.send_stream("NEW", StreamCommand("stop", 7))
    assert await hub.send_stream("NEW", StreamCommand("volume", volume=0.8))
    assert new.sent_json() == [
        {
            "type": "stream_start",
            "stream": 7,
            "path": "/device/stream/t",
            "rate": 16000,
            "volume": 0.5,
            "live": True,
        },
        {"type": "stream_stop", "stream": 7},
        {"type": "stream_volume", "value": 0.8},
    ]
    assert not await hub.send_stream("GONE", start)


async def test_reports_and_disconnect_reach_listener() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock())
    got: list[tuple[str, StreamReport | None]] = []
    hub.use_stream_listener(lambda device, report: got.append((device, report)))
    conn, _ = await connect(hub, "NEW", protocol=5)
    await eventually(lambda: hub.supports_stream("NEW"))
    conn.feed_json("stream_status", stream=7, state="playing", played=32000, error="")
    conn.feed_json("stream_status", stream=7, state="bogus", played=1)  # мусор — мимо
    conn.feed_json("stream_status", stream=7, state="failed", played=0, error="download")
    await eventually(lambda: len(got) == 2)
    assert got == [
        ("NEW", StreamReport(7, "playing", 32000, "")),
        ("NEW", StreamReport(7, "failed", 0, "download")),
    ]
    conn.fail()
    await eventually(lambda: len(got) == 3)
    assert got[-1] == ("NEW", None)


async def test_listener_failure_does_not_break_hub() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock())

    def broken(device: str, report: StreamReport | None) -> None:
        raise RuntimeError("упал")

    hub.use_stream_listener(broken)
    conn, _ = await connect(hub, "NEW", protocol=5)
    await eventually(lambda: hub.supports_stream("NEW"))
    conn.feed_json("stream_status", stream=1, state="ended", played=0)
    conn.feed_json("update_status", what="model", state="progress", done=1, total=2, error="")
    await eventually(lambda: next(d for d in hub.devices() if d.device_id == "NEW").update is not None)


def test_parse_stream_status() -> None:
    assert parse_message('{"type":"stream_status","stream":3,"state":"ended","played":5}') == StreamReport(
        3, "ended", 5, ""
    )
    for bad in (
        '{"type":"stream_status","stream":-1,"state":"ended","played":5}',
        '{"type":"stream_status","stream":3,"state":"ended","played":true}',
        '{"type":"stream_status","stream":3,"state":"paused","played":5}',
    ):
        assert parse_message(bad) is None
