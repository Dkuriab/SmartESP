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


async def test_play_frozen_clock_sends_only_burst() -> None:
    # время стоит: со скоростью сети уходит только первая ~1 с, дальше темп (см. test_pacer)
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    audio = chunks(*[bytes(SECOND)] * 30)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(hub.play("A", 1, audio), 0.2)
    sent = len(conn.sent_audio())
    assert SECOND <= sent <= SECOND + 4096
    assert '{"type":"reply_end","turn":1}' not in conn.sent


async def test_play_resumes_as_time_passes() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    task = asyncio.create_task(hub.play("A", 1, chunks(*[bytes(SECOND)] * 5)))
    for _ in range(10):
        before = len(conn.sent_audio())
        clock.now += 1.0
        await eventually(lambda before=before: len(conn.sent_audio()) > before or task.done())
        if task.done():
            break
    await asyncio.wait_for(task, 1)
    assert len(conn.sent_audio()) == 5 * SECOND
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

    new, _ = await accepted_turn(hub, clock, "A", turn=1, turn_id=2)
    await hub.play("A", 1, chunks(bytes(100)))  # старый ход хаба — ничего не уходит
    assert new.sent == []
    await hub.play("A", 2, chunks(bytes(100)))
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


async def test_late_first_chunk_gives_no_credit() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    gate = asyncio.Event()

    async def audio() -> AsyncIterator[bytes]:
        await gate.wait()  # TTS долго готовит первый кусок, колонка молчит
        for _ in range(60):
            yield bytes(SECOND)

    task = asyncio.create_task(hub.play("A", 1, audio()))
    await asyncio.sleep(0.02)
    clock.now += 25.0
    gate.set()
    await eventually(lambda: len(conn.sent_audio()) >= SECOND)
    await asyncio.sleep(0.1)
    assert len(conn.sent_audio()) <= SECOND + 4096  # только первая секунда, без «накопленного»
    task.cancel()


async def test_mid_stream_gap_gives_no_credit() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    gate = asyncio.Event()
    half = SECOND // 2

    async def audio() -> AsyncIterator[bytes]:
        yield bytes(half)
        await gate.wait()  # пауза посреди ответа длиннее уже отправленного звука
        for _ in range(60):
            yield bytes(SECOND)

    task = asyncio.create_task(hub.play("A", 1, audio()))
    await eventually(lambda: len(conn.sent_audio()) == half)
    clock.now += 20.0
    gate.set()
    await eventually(lambda: len(conn.sent_audio()) >= half + SECOND)
    await asyncio.sleep(0.1)
    assert len(conn.sent_audio()) <= half + SECOND + 4096
    task.cancel()


async def test_early_stop_closes_audio_source() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    closed = asyncio.Event()

    async def audio() -> AsyncIterator[bytes]:
        try:
            yield bytes(100)
            conn.feed_json("barge_in", turn=1)
            await asyncio.sleep(0.05)
            yield bytes(100)
            yield bytes(100)
        finally:
            closed.set()

    await asyncio.wait_for(hub.play("A", 1, audio()), 1)
    assert closed.is_set()
    assert len(conn.sent_audio()) == 100


async def test_inactive_turn_closes_audio_source() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    conn, _ = await accepted_turn(hub, clock, "A")
    closed = asyncio.Event()

    async def audio() -> AsyncIterator[bytes]:
        try:
            yield bytes(100)
        finally:
            closed.set()

    source = audio()
    await anext(source)  # генератор начат: aclose() выполнит его finally
    await hub.play("A", 2, source)  # ход хаба 2 не активен — ничего не шлём, но источник закрываем
    assert closed.is_set()
    assert conn.sent == []
