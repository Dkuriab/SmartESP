"""Тесты хаба: прослушивание по команде ядра (listen), listen_after, последняя колонка."""

import asyncio

import pytest
from hub_helpers import FRAME, WINDOW_S, FakeClock, accepted_turn, chunks, connect, eventually, make_hub

from fakes.fake_connection import FakeConnection
from smartesp.devices import DeviceHub

T1 = 0x80000001  # первый ход ядра в сессии колонки
T2 = 0x80000002
LISTEN_T1 = {"type": "listen", "turn": T1}


async def v3(hub: DeviceHub, device_id: str = "A") -> FakeConnection:
    """Подключает колонку с протоколом 3 и ждёт, пока хаб её узнает."""
    conn, _ = await connect(hub, device_id, protocol=3)
    await eventually(lambda: hub.supports_proactive(device_id))
    return conn


async def no_utterance(hub: DeviceHub) -> None:
    """Проверяет, что в очереди нет вопроса."""
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(hub.next_utterance(), 0.1)


def listens(conn: FakeConnection) -> list[int]:
    """Номера ходов в отправленных колонке кадрах listen."""
    return [m["turn"] for m in conn.sent_json() if m["type"] == "listen"]


async def test_listen_emits_utterance() -> None:
    clock = FakeClock()
    clock.now = 50.0
    hub = make_hub(clock)
    conn = await v3(hub)
    assert await hub.listen("A") is True
    assert conn.sent_json() == [LISTEN_T1]
    assert hub.is_active("A", 1)  # ход хаба выдан сразу, без арбитра
    conn.feed(FRAME)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=T1, reason="vad")
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)  # часы стоят: окно арбитра не нужно
    assert (utterance.device_id, utterance.turn, len(utterance.pcm)) == ("A", 1, 2048)
    assert (utterance.origin, utterance.started_at) == ("listen", 50.0)
    assert hub.is_active("A", 1)


async def test_listen_busy_drops_recording() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn = await v3(hub)
    assert await hub.listen("A")
    conn.feed_json("busy", turn=T1)
    await eventually(lambda: not hub.is_active("A", 1))
    await no_utterance(hub)
    conn.feed_json("wake", turn=1, level=-30.0)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=1, reason="vad")
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert (utterance.turn, utterance.origin, len(utterance.pcm)) == (2, "wake", 1024)


async def test_wake_between_playback_done_and_listen() -> None:
    # слово прозвучало раньше, чем колонка получила listen: wake, затем busy
    clock = FakeClock()
    hub = make_hub(clock)
    conn = await v3(hub)
    assert await hub.listen("A")
    conn.feed_json("wake", turn=1, level=-30.0)
    conn.feed_json("busy", turn=T1)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=1, reason="vad")
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert (utterance.turn, utterance.origin, len(utterance.pcm)) == (2, "wake", 1024)
    assert not hub.is_active("A", 1)


async def test_listen_no_speech() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    assert await hub.listen("A")
    conn.feed_json("utterance_end", turn=T1, reason="no_speech")
    await eventually(lambda: not hub.is_active("A", 1))
    await no_utterance(hub)


async def test_listen_refused_while_turn_goes() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A", protocol=3)
    assert await hub.listen("A") is False
    assert conn.sent_json() == []
    assert hub.is_active("A", 1)


async def test_listen_turn_loses_to_new_wake_elsewhere() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a = await v3(hub, "A")
    assert await hub.listen("A")
    conn_b, _ = await connect(hub, "B")
    conn_b.feed_json("wake", turn=1, level=-30.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: {"type": "cancel_turn", "turn": T1} in conn_a.sent_json())
    assert not hub.is_active("A", 1)
    assert hub.is_active("B", 2)


async def test_listen_after_waits_playback_done() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A", protocol=3)
    conn.feed_json("utterance_end", turn=1, reason="vad")
    await asyncio.wait_for(hub.next_utterance(), 1)
    await hub.play("A", 1, chunks(bytes(100)))
    task = asyncio.create_task(hub.listen_after("A", 1))
    conn.feed_json("playback_done", turn=2)  # чужой ход — не он
    await asyncio.sleep(0.05)
    assert not task.done() and listens(conn) == []
    conn.feed_json("playback_done", turn=1)
    await asyncio.wait_for(task, 1)
    assert listens(conn) == [T1]
    assert hub.is_active("A", 2)


async def test_listen_after_barge_in_does_nothing() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A", protocol=3)
    task = asyncio.create_task(hub.listen_after("A", 1))
    await asyncio.sleep(0.01)
    conn.feed_json("barge_in", turn=1)
    await asyncio.wait_for(task, 1)
    assert listens(conn) == []


async def test_listen_after_disconnect_returns() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A", protocol=3)
    task = asyncio.create_task(hub.listen_after("A", 1))
    await asyncio.sleep(0.01)
    conn.fail()
    await asyncio.wait_for(task, 1)
    assert listens(conn) == []


async def test_listen_after_ended_or_v2_turn_returns_at_once() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")  # протокол 2
    await asyncio.wait_for(hub.listen_after("A", 1), 0.1)
    await asyncio.wait_for(hub.listen_after("A", 7), 0.1)  # такого хода нет
    await asyncio.wait_for(hub.listen_after("B", 1), 0.1)  # такой колонки нет
    assert conn.sent_json() == []


async def test_last_active_device() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    assert hub.last_active_device() is None
    await accepted_turn(hub, clock, "A")
    assert hub.last_active_device() == "A"
    conn_b = await v3(hub, "B")
    assert hub.last_active_device() == "A"  # просто подключилась — не ход
    assert await hub.listen("B")
    assert hub.last_active_device() == "B"
    conn_b.fail()
    await eventually(lambda: not hub.supports_proactive("B"))
    assert hub.last_active_device() is None


async def test_core_turn_numbers_per_session() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    assert await hub.listen("A")
    conn.feed_json("busy", turn=T1)
    await eventually(lambda: not hub.is_active("A", 1))
    assert await hub.listen("A")
    assert listens(conn) == [T1, T2]
    conn.fail()
    await eventually(lambda: not hub.supports_proactive("A"))
    conn2 = await v3(hub)  # новая сессия той же колонки
    assert await hub.listen("A")
    assert listens(conn2) == [T1]
