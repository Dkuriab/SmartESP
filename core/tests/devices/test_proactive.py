"""Тесты хаба: объявления по инициативе ядра (протокол v3) и их итог доставки."""

import asyncio
from collections.abc import AsyncIterator

from hub_helpers import LATE_S, WINDOW_S, FakeClock, accepted_turn, chunks, connect, eventually, make_hub

from fakes.fake_connection import FakeConnection
from fakes.fake_device_port import FakeDevicePort
from smartesp.contracts import DevicePort
from smartesp.devices import DeviceHub

T1 = 0x80000001  # первый ход ядра в сессии колонки
ANNOUNCE_T1 = '{"type":"announce","turn":2147483649}'
REPLY_END_T1 = '{"type":"reply_end","turn":2147483649}'


async def v3(hub: DeviceHub, device_id: str = "A") -> FakeConnection:
    """Подключает колонку с протоколом 3 и ждёт, пока хаб её узнает."""
    conn, _ = await connect(hub, device_id, protocol=3)
    await eventually(lambda: hub.supports_proactive(device_id))
    return conn


class Gated:
    """Звук объявления: первый кусок сразу, второй — только после open()."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()

    def open(self) -> None:
        self.gate.set()

    async def audio(self) -> AsyncIterator[bytes]:
        yield b"\x01" * 100
        await self.gate.wait()
        yield b"\x02" * 100


async def test_announce_delivered() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    task = asyncio.create_task(hub.announce("A", chunks(b"\x01" * 100, b"\x02" * 100)))
    await eventually(lambda: REPLY_END_T1 in conn.sent)
    assert conn.sent == [
        ANNOUNCE_T1,
        '{"type":"tone","name":"attention"}',
        '{"type":"reply_start","turn":2147483649}',
        b"\x01" * 100,
        b"\x02" * 100,
        REPLY_END_T1,
    ]
    await asyncio.sleep(0.02)
    assert not task.done()  # ждёт, пока колонка доиграет
    conn.feed_json("playback_done", turn=T1)
    assert await asyncio.wait_for(task, 1) == "delivered"
    assert not hub.is_active("A", 1)


async def test_announce_busy() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    gated = Gated()
    task = asyncio.create_task(hub.announce("A", gated.audio()))
    await eventually(lambda: b"\x01" * 100 in conn.sent)
    conn.feed_json("busy", turn=T1)
    assert await asyncio.wait_for(task, 1) == "busy"  # сразу, не дожидаясь звука
    gated.open()
    await asyncio.sleep(0.02)
    assert b"\x02" * 100 not in conn.sent and REPLY_END_T1 not in conn.sent
    assert not hub.is_active("A", 1)


async def test_announce_barge_in_is_interrupted() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    task = asyncio.create_task(hub.announce("A", chunks(bytes(100))))
    await eventually(lambda: REPLY_END_T1 in conn.sent)
    conn.feed_json("barge_in", turn=T1)
    assert await asyncio.wait_for(task, 1) == "interrupted"


async def test_announce_lost_on_disconnect() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    gated = Gated()
    task = asyncio.create_task(hub.announce("A", gated.audio()))
    await eventually(lambda: b"\x01" * 100 in conn.sent)
    conn.fail()
    assert await asyncio.wait_for(task, 1) == "lost"  # звук ещё не кончился, но ждать нечего


async def test_announce_lost_without_playback_done() -> None:
    hub = DeviceHub(WINDOW_S, LATE_S, {}, clock=FakeClock(), reply_grace_s=0.05)
    conn = await v3(hub)
    result = await asyncio.wait_for(hub.announce("A", chunks(bytes(100))), 1)
    assert result == "lost"
    assert not hub.is_active("A", 1)
    assert conn.sent_json()[-1] == {"type": "cancel_turn", "turn": T1}  # колонку возвращаем в покой
    conn.feed_json("playback_done", turn=T1)  # опоздавший итог ничего не ломает
    await asyncio.sleep(0.02)


async def test_announce_audio_error_is_lost() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)

    async def broken() -> AsyncIterator[bytes]:
        yield bytes(100)
        raise RuntimeError("tts failed")

    assert await asyncio.wait_for(hub.announce("A", broken()), 1) == "lost"
    assert conn.sent_json()[-1] == {"type": "cancel_turn", "turn": T1}
    assert not hub.is_active("A", 1)


async def test_announce_not_arbitrated() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a = await v3(hub, "A")
    task = asyncio.create_task(hub.announce("A", chunks(bytes(100))))
    await eventually(lambda: REPLY_END_T1 in conn_a.sent)
    clock.now += 5.0
    conn_b, _ = await connect(hub, "B")
    conn_b.feed_json("wake", turn=1, level=-10.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("B", 2))  # ход B принят (ход объявления — 1)
    await asyncio.sleep(0.1)
    assert all(m.get("type") != "cancel_turn" for m in conn_a.sent_json())
    assert hub.is_active("A", 1)
    conn_a.feed_json("playback_done", turn=T1)
    assert await asyncio.wait_for(task, 1) == "delivered"


async def test_announce_on_busy_session_sends_nothing() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A", protocol=3)
    assert await hub.announce("A", chunks(bytes(100))) == "busy"  # у хаба идёт ход по слову
    assert conn.sent == []
    assert hub.is_active("A", 1)


async def test_wake_before_announce_reaches_device_is_busy() -> None:
    # колонка проснулась раньше, чем получила announce: wake приходит без barge_in
    clock = FakeClock()
    hub = make_hub(clock)
    conn = await v3(hub)
    gated = Gated()
    task = asyncio.create_task(hub.announce("A", gated.audio()))
    await eventually(lambda: b"\x01" * 100 in conn.sent)
    conn.feed_json("wake", turn=1, level=-30.0)
    conn.feed_json("busy", turn=T1)
    assert await asyncio.wait_for(task, 1) == "busy"
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("A", 2))  # ход по слову идёт обычным путём


async def test_v2_not_proactive() -> None:
    hub = make_hub(FakeClock())
    conn, _ = await connect(hub, "A")
    await eventually(lambda: bool(hub.devices()) and hub.devices()[0].connected)
    assert not hub.supports_proactive("A")
    assert await hub.listen("A") is False
    assert await hub.announce("A", chunks(bytes(100))) == "lost"
    assert not hub.supports_proactive("B")
    assert await hub.announce("B", chunks(bytes(100))) == "lost"  # не подключена
    assert conn.sent == []


async def test_announce_closes_audio_when_refused() -> None:
    hub = make_hub(FakeClock())
    closed: list[bool] = []

    async def audio() -> AsyncIterator[bytes]:
        try:
            yield bytes(100)
        finally:
            closed.append(True)

    stream = audio()
    await anext(stream)  # генератор начат: закрытие запустит finally
    assert await hub.announce("A", stream) == "lost"
    assert closed == [True]


async def test_device_info_protocol() -> None:
    hub = make_hub(FakeClock())
    await v3(hub)
    assert hub.devices()[0].protocol == 3


async def test_fake_port_proactive() -> None:
    port: DevicePort = (fake := FakeDevicePort())
    fake.deliveries = ["busy"]
    assert await port.announce("A", chunks(b"\x01")) == "lost"  # не v3
    fake.proactive = {"A"}
    assert await port.announce("A", chunks(b"\x01")) == "busy"
    assert await port.announce("A", chunks(b"\x02")) == "delivered"
    assert [(c.audio, c.result) for c in fake.announces] == [
        (b"", "lost"),
        (b"\x01", "busy"),
        (b"\x02", "delivered"),
    ]
    assert await port.listen("A") and not await port.listen("B")
    await port.listen_after("A", 3)
    assert (fake.listens, fake.listen_afters, port.last_active_device()) == (["A"], [("A", 3)], None)
