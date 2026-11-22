"""Хаб: калибровка эха (возможность «echo», прошивка 0.7.0) и частота потоков из hello."""

import asyncio

import pytest
from hub_helpers import LATE_S, WINDOW_S, FakeClock, eventually

from fakes.fake_connection import FakeConnection
from fakes.fake_events import RecordingSink
from smartesp.contracts import EchoRefusedError
from smartesp.devices import DeviceHub, parse_message
from smartesp.devices.hello import Hello

_TASKS: list[asyncio.Task[None]] = []


async def connect(hub: DeviceHub, device_id: str, **hello: object) -> FakeConnection:
    conn = FakeConnection()
    _TASKS.append(asyncio.create_task(hub.handle(conn)))  # задачи соединений живут до конца теста
    conn.feed_json("hello", fw="0.7.0", device_id=device_id, protocol=5, **hello)
    await eventually(lambda: hub.supports_stream(device_id))
    return conn


def info(hub: DeviceHub, device_id: str):  # noqa: ANN201 — DeviceInfo
    return next(d for d in hub.devices() if d.device_id == device_id)


def test_hello_stream_rates_parsed() -> None:
    hello = parse_message(
        '{"type":"hello","fw":"0.7.0","device_id":"A","protocol":5,"stream_rates":[48000,16000,48000,true,"x",0]}'
    )
    assert isinstance(hello, Hello) and hello.stream_rates == (16000, 48000)
    old = parse_message('{"type":"hello","fw":"0.6.0","device_id":"A","protocol":5}')
    assert isinstance(old, Hello) and old.stream_rates == ()


async def test_stream_rate_is_highest_common() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock())
    await connect(hub, "NEW", stream_rates=[16000, 48000])
    await connect(hub, "OLD")
    await connect(hub, "ODD", stream_rates=[44100, 16000])
    assert (hub.stream_rate("NEW"), hub.stream_rate("OLD"), hub.stream_rate("ODD")) == (48000, 16000, 16000)


async def test_calibration_command_status_and_event() -> None:
    events = RecordingSink()
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock(), events=events)
    conn = await connect(hub, "A", caps=["sounds", "echo"])
    conn.feed_json("echo_status", state="current", delay_ms=20, previous_ms=20, confidence=0, error="")
    await eventually(lambda: info(hub, "A").echo is not None)
    assert info(hub, "A").echo.delay_ms == 20  # type: ignore[union-attr]
    await hub.calibrate_echo("A")
    assert conn.sent_json()[-1] == {"type": "echo_calibrate"}
    assert info(hub, "A").echo.state == "sent"  # type: ignore[union-attr]
    with pytest.raises(EchoRefusedError, match="уже идёт"):
        await hub.calibrate_echo("A")
    conn.feed_json("echo_status", state="done", delay_ms=27, previous_ms=20, confidence=0.71, error="")
    await eventually(lambda: info(hub, "A").echo.state == "done")  # type: ignore[union-attr]
    echo = info(hub, "A").echo
    assert echo is not None and (echo.delay_ms, echo.previous_ms, echo.confidence) == (27, 20, 0.71)
    published = [data for kind, data in events.events if kind == "device_echo"]
    assert [d["state"] for d in published] == ["current", "sent", "done"] and published[-1][
        "device_id"
    ] == "A"
    conn.feed_json("echo_status", state="done", delay_ms=999, previous_ms=20, confidence=0.5)  # мусор
    await hub.set_echo_delay("A", 35)
    assert conn.sent_json()[-1] == {"type": "echo_delay", "delay_ms": 35}
    assert info(hub, "A").echo.delay_ms == 27  # type: ignore[union-attr]


async def test_calibration_refusals() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock())
    with pytest.raises(EchoRefusedError, match="не подключена"):
        await hub.calibrate_echo("NOPE")
    old = await connect(hub, "OLD", caps=["sounds"])
    with pytest.raises(EchoRefusedError, match="0.7.0"):
        await hub.calibrate_echo("OLD")
    assert all(m["type"] != "echo_calibrate" for m in old.sent_json())
    conn = await connect(hub, "A", caps=["echo"])
    with pytest.raises(EchoRefusedError, match="от 0 до 300"):
        await hub.set_echo_delay("A", 301)
    conn.feed_json("wake", turn=1, level=-30.0)  # идёт разговор
    await eventually(lambda: hub.is_busy("A"))
    with pytest.raises(EchoRefusedError, match="занята"):
        await hub.calibrate_echo("A")
