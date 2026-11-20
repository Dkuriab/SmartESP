"""Тесты хаба колонок: сессии, арбитраж, сбор вопросов, конец хода."""

import asyncio

import pytest
from hub_helpers import FRAME, WINDOW_S, FakeClock, accepted_turn, chunks, connect, eventually, make_hub

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
    await eventually(lambda: {"type": "cancel_turn", "turn": 1} in conn_a.sent_json())
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
    # turn — номер хода в хабе (первый принятый — 1), не номер колонки
    assert (utterance.device_id, utterance.turn, len(utterance.pcm)) == ("legacy:10.0.0.9:777", 1, 1024)
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


async def test_played_does_not_end_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    conn.feed_json("played", turn=1, bytes=16000)  # прогресс ответа: ход не заканчивает
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
    await eventually(lambda: hub.is_active("A", 2))  # второй принятый ход хаба


async def test_new_wake_elsewhere_cancels_active_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, _ = await accepted_turn(hub, clock, "A")
    clock.now += 5.0  # за пределами «позднего» окна
    conn_b, _ = await connect(hub, "B")
    conn_b.feed_json("wake", turn=1, level=-30.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("B", 2))  # второй принятый ход хаба
    assert not hub.is_active("A", 1)
    await eventually(lambda: {"type": "cancel_turn", "turn": 1} in conn_a.sent_json())


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


async def test_reconnect_after_reboot_gets_new_turn_id() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    old, _ = await accepted_turn(hub, clock, "A")
    old.feed_json("utterance_end", turn=1, reason="vad")
    first = await asyncio.wait_for(hub.next_utterance(), 1)
    clock.now += 5.0
    new, _ = await accepted_turn(hub, clock, "A", turn=1, turn_id=2)  # после перезагрузки ESP снова с 1
    new.feed_json("utterance_end", turn=1, reason="vad")
    second = await asyncio.wait_for(hub.next_utterance(), 1)
    assert (first.turn, second.turn) == (1, 2)
    assert not hub.is_active("A", first.turn)
    assert hub.is_active("A", second.turn)
    await hub.play("A", first.turn, chunks(bytes(100)))
    assert new.sent == []
    await hub.play("A", second.turn, chunks(bytes(100)))
    assert new.sent_json() == [{"type": "reply_start", "turn": 1}, {"type": "reply_end", "turn": 1}]


async def test_stuck_speaker_does_not_stall_arbitration() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, _ = await accepted_turn(hub, clock, "A")
    conn_a.stall()  # Wi-Fi пропал: отправка висит, замок отправки занят
    play = asyncio.create_task(hub.play("A", 1, chunks(bytes(4096), bytes(4096))))
    await asyncio.sleep(0.02)
    clock.now += 5.0
    conn_b, _ = await accepted_turn(hub, clock, "B", turn_id=2)  # cancel_turn для A повис в фоне
    assert not hub.is_active("A", 1)
    conn_b.feed_json("playback_done", turn=1)
    clock.now += 5.0
    await accepted_turn(hub, clock, "C", turn_id=3)
    conn_a.release()
    await asyncio.wait_for(play, 1)
    await eventually(lambda: {"type": "cancel_turn", "turn": 1} in conn_a.sent_json())
    assert conn_a.sent_audio() == b""  # повис reply_start; после отмены звук не шлётся
    assert '{"type":"reply_end","turn":1}' not in conn_a.sent


async def test_aclose_stops_timer_and_background_sends() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn_a, task_a = await connect(hub, "A")
    conn_b, task_b = await connect(hub, "B")
    conn_b.stall()  # cancel_turn для B повиснет в фоне
    conn_a.feed_json("wake", turn=1, level=-20.0)
    conn_b.feed_json("wake", turn=1, level=-40.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active("A", 1))
    await asyncio.sleep(0.01)
    handlers = {task_a, task_b}
    pending = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()} - handlers
    assert any(not t.done() for t in pending)  # таймер арбитра и повисшая отправка

    await asyncio.wait_for(hub.aclose(), 1)
    await hub.aclose()  # повторно — без ошибок

    assert all(t.done() for t in pending)
    for task in handlers:
        task.cancel()
    await asyncio.gather(*handlers, return_exceptions=True)
