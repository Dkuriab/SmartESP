"""Ход ответа на колонке: played_bytes по событиям played и по оценке темпа."""

import asyncio

from hub_helpers import SECOND, FakeClock, accepted_turn, chunks, eventually, make_hub


async def test_no_position_before_reply_or_for_other_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    await accepted_turn(hub, clock, "A")
    assert hub.played_bytes("A", 1) is None
    assert hub.played_bytes("B", 1) is None


async def test_position_estimated_by_pacing_without_played() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks(bytes(SECOND // 2)))  # полсекунды ушло сразу
    assert hub.played_bytes("A", 1) == 0  # время стоит — ничего не прозвучало
    clock.now += 0.25
    assert hub.played_bytes("A", 1) == SECOND // 4
    clock.now += 5
    assert hub.played_bytes("A", 1) == SECOND // 2  # не больше отправленного


async def test_position_follows_played_events_of_active_turn() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks(bytes(SECOND)))
    conn.feed_json("played", turn=7, bytes=1000)  # чужой ход колонки — мимо
    conn.feed_json("played", turn=1, bytes=8000)
    await eventually(lambda: hub.played_bytes("A", 1) == 8000)
    conn.feed_json("played", turn=1, bytes=10 * SECOND)  # больше отправленного не бывает
    await eventually(lambda: hub.played_bytes("A", 1) == SECOND)


async def test_position_gone_after_playback_done() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks(bytes(100)))
    conn.feed_json("playback_done", turn=1)
    await eventually(lambda: not hub.is_active("A", 1))
    await asyncio.sleep(0)
    assert hub.played_bytes("A", 1) is None
