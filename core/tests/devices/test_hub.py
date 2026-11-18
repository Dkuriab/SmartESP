"""Тесты хаба колонок: сессии, арбитраж, сбор вопросов, конец хода."""

import asyncio

import pytest
from hub_helpers import FRAME, WINDOW_S, FakeClock, accepted_turn, connect, eventually, make_hub

from fakes.fake_connection import FakeConnection
from smartesp.contracts import DevicePort, Utterance
from smartesp.devices import DeviceHub


async def no_utterance(hub: DeviceHub) -> None:
    """Проверяет, что в очереди нет вопроса."""
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(hub.next_utterance(), 0.1)


def test_hub_satisfies_device_port() -> None:
    port: DevicePort = make_hub(FakeClock())
    assert port.device_name("A") == "Кухня"
    assert port.device_name("B") == "B"


async def test_utterance_from_single_device() -> None:
    clock = FakeClock()
    clock.now = 100.0
    hub = make_hub(clock)
    conn, _ = await connect(hub, "A")
    conn.feed_json("wake", turn=1, level=-30.0)
    for _ in range(3):
        conn.feed(FRAME)
    await asyncio.sleep(0.01)
    clock.now += 0.4
    conn.feed_json("utterance_end", turn=1, reason="vad")
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert utterance == Utterance(device_id="A", turn=1, pcm=bytes(3072), started_at=100.0)
    assert hub.is_active("A", 1)


async def test_audio_after_accept_is_collected() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.feed(FRAME)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=1, reason="timeout")
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert len(utterance.pcm) == 2048


async def test_no_speech_dropped() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=1, reason="no_speech")
    await eventually(lambda: not hub.is_active("A", 1))
    await no_utterance(hub)


async def test_loser_gets_cancel_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, _ = await connect(hub, "A")
    conn_b, _ = await connect(hub, "B")
    conn_a.feed_json("wake", turn=1, level=-40.0)
    conn_b.feed_json("wake", turn=1, level=-25.0)
    for conn in (conn_a, conn_b):
        conn.feed(FRAME)
        conn.feed_json("utterance_end", turn=1, reason="vad")
    await asyncio.sleep(0.01)
    clock.now += 0.4
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert (utterance.device_id, len(utterance.pcm)) == ("B", 1024)
    assert {"type": "cancel_turn", "turn": 1} in conn_a.sent_json()
    assert conn_b.sent_json() == []
    assert not hub.is_active("A", 1)
    await no_utterance(hub)


async def test_late_wake_cancelled() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    await accepted_turn(hub, clock, "A")
    conn_b, _ = await connect(hub, "B")
    conn_b.feed_json("wake", turn=4, level=-10.0)
    await eventually(lambda: {"type": "cancel_turn", "turn": 4} in conn_b.sent_json())
    assert hub.is_active("A", 1)


async def test_messages_before_hello_ignored() -> None:
    hub = make_hub(FakeClock())
    conn = FakeConnection()
    asyncio.create_task(hub.handle(conn))
    conn.feed_json("wake", turn=1)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=1, reason="vad")
    conn.feed_json("hello", fw="1.0")
    await no_utterance(hub)


async def test_legacy_device_id_and_immediate_accept() -> None:
    hub = make_hub(FakeClock())  # часы стоят: v1 принимается без окна арбитража
    conn, _ = await connect(hub, None, remote="10.0.0.9:777")
    conn.feed_json("wake", turn=2)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=2, reason="vad")
    utterance = await asyncio.wait_for(hub.next_utterance(), 1)
    assert (utterance.device_id, utterance.turn, len(utterance.pcm)) == ("legacy:10.0.0.9:777", 2, 1024)
    assert hub.device_name("legacy:10.0.0.9:777") == "legacy:10.0.0.9:777"


async def test_playback_done_ends_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.feed_json("playback_done", turn=2)  # чужой ход — не трогает
    await asyncio.sleep(0.02)
    assert hub.is_active("A", 1)
    conn.feed_json("playback_done", turn=1)
    await eventually(lambda: not hub.is_active("A", 1))


async def test_newer_turn_ends_previous() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.feed_json("barge_in", turn=1)
    conn.feed_json("wake", turn=2, level=-20.0)
    await eventually(lambda: not hub.is_active("A", 1))
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("A", 2))


async def test_new_wake_elsewhere_cancels_active_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, _ = await accepted_turn(hub, clock, "A")
    clock.now += 5.0  # за пределами «позднего» окна
    conn_b, _ = await connect(hub, "B")
    conn_b.feed_json("wake", turn=1, level=-30.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("B", 1))
    assert not hub.is_active("A", 1)
    assert {"type": "cancel_turn", "turn": 1} in conn_a.sent_json()


async def test_reconnect_same_id_replaces_session() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    old, _ = await accepted_turn(hub, clock, "A")
    new, _ = await connect(hub, "A")
    await eventually(lambda: old.closed)
    assert not hub.is_active("A", 1)
    await hub.send_tone("A", "wake")
    assert new.sent_json() == [{"type": "tone", "name": "wake"}]
    assert old.sent_json() == []


async def test_disconnect_ends_handle_and_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.fail()
    await eventually(lambda: not hub.is_active("A", 1))
    await hub.send_tone("A", "error")  # колонки нет — тихо ничего


async def test_cancel_to_dropped_connection_does_not_break_hub() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, task_a = await connect(hub, "A")
    conn_b, _ = await connect(hub, "B")
    conn_a.feed_json("wake", turn=1, level=-40.0)
    conn_b.feed_json("wake", turn=1, level=-25.0)
    await asyncio.sleep(0.01)
    conn_a.closed = True  # отправка упадёт, но receive ещё ждёт
    clock.now += 0.4
    await eventually(lambda: hub.is_active("B", 1))
    assert not task_a.done()
    conn_b.feed_json("utterance_end", turn=1, reason="vad")
    assert (await asyncio.wait_for(hub.next_utterance(), 1)).device_id == "B"
