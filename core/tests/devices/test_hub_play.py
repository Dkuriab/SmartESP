"""Тесты хаба колонок: отправка ответа с темпом и обрывы."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from hub_helpers import SECOND, FakeClock, accepted_turn, chunks, connect, eventually, make_hub


def reply_frames(sent: list[str | bytes]) -> list[str | bytes]:
    """Исходящие после hello-обмена: только кадры ответа и звук."""
    return [m for m in sent if isinstance(m, bytes) or '"reply_' in m]


async def test_play_sends_reply_frames() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks(b"\x01" * 1000, b"\x02" * 1000, b"\x03" * 1000))
    assert reply_frames(conn.sent) == [
        '{"type":"reply_start","turn":1}',
        b"\x01" * 1000,
        b"\x02" * 1000,
        b"\x03" * 1000,
        '{"type":"reply_end","turn":1}',
    ]


async def test_play_splits_large_chunks() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks(bytes(10000)))
    assert [len(m) for m in conn.sent if isinstance(m, bytes)] == [4096, 4096, 1808]


async def test_play_empty_reply() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 1, chunks())
    assert conn.sent_json() == [{"type": "reply_start", "turn": 1}, {"type": "reply_end", "turn": 1}]


async def test_play_inactive_turn_sends_nothing() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    await hub.play("A", 2, chunks(bytes(100)))
    await hub.play("B", 1, chunks(bytes(100)))
    assert conn.sent == []


async def test_play_paced_10s_ahead() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    audio = chunks(*[bytes(SECOND)] * 30)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(hub.play("A", 1, audio), 0.2)
    sent = len(conn.sent_audio())
    assert 10 * SECOND - 4096 <= sent <= 10 * SECOND + 4096
    assert '{"type":"reply_end","turn":1}' not in conn.sent


async def test_play_resumes_as_time_passes() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    task = asyncio.create_task(hub.play("A", 1, chunks(*[bytes(SECOND)] * 30)))
    await eventually(lambda: len(conn.sent_audio()) >= 10 * SECOND - 4096)
    clock.now += 5.0
    await eventually(lambda: len(conn.sent_audio()) >= 15 * SECOND - 4096)
    assert len(conn.sent_audio()) <= 15 * SECOND + 4096
    clock.now += 100.0
    await asyncio.wait_for(task, 1)
    assert len(conn.sent_audio()) == 30 * SECOND
    assert conn.sent[-1] == '{"type":"reply_end","turn":1}'


async def test_barge_in_stops_play() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    task = asyncio.create_task(hub.play("A", 1, chunks(*[bytes(SECOND)] * 30)))
    await eventually(lambda: len(conn.sent_audio()) > 0)
    conn.feed_json("barge_in", turn=1)
    await eventually(lambda: not hub.is_active("A", 1))
    await asyncio.wait_for(task, 1)
    assert '{"type":"reply_end","turn":1}' not in conn.sent


async def test_disconnect_mid_reply() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, handle_task = await accepted_turn(hub, clock, "A")

    async def audio() -> AsyncIterator[bytes]:
        yield bytes(4096)
        conn.fail()
        yield bytes(4096)
        yield bytes(4096)

    await asyncio.wait_for(hub.play("A", 1, audio()), 1)
    assert len(conn.sent_audio()) == 4096
    await asyncio.wait_for(handle_task, 1)
    assert not hub.is_active("A", 1)

    new, _ = await accepted_turn(hub, clock, "A", turn=1)
    await hub.play("A", 1, chunks(bytes(100)))
    assert new.sent_json() == [{"type": "reply_start", "turn": 1}, {"type": "reply_end", "turn": 1}]


async def test_play_stops_when_connection_replaced() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    old, _ = await accepted_turn(hub, clock, "A")
    task = asyncio.create_task(hub.play("A", 1, chunks(*[bytes(SECOND)] * 30)))
    await eventually(lambda: len(old.sent_audio()) > 0)
    new, _ = await connect(hub, "A")
    await asyncio.wait_for(task, 1)
    assert new.sent == []


async def test_audio_source_error_propagates() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")

    async def audio() -> AsyncIterator[bytes]:
        yield bytes(100)
        raise ConnectionError("tts down")

    with pytest.raises(ConnectionError, match="tts down"):
        await hub.play("A", 1, audio())
    assert hub.is_active("A", 1)
    assert '{"type":"reply_end","turn":1}' not in conn.sent
