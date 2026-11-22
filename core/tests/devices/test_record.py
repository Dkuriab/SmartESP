"""Тесты хаба: запись одной фразы для обучения (record) — мимо разговора."""

import asyncio

from hub_helpers import FRAME, FakeClock, accepted_turn, eventually, make_hub
from test_proactive_listen import T1, no_utterance, v3


async def test_record_returns_audio_and_ends_turn_silently() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    task = asyncio.create_task(hub.record("A"))
    await eventually(lambda: any(m["type"] == "listen" for m in conn.sent_json()))
    conn.feed(FRAME)
    conn.feed(FRAME)
    conn.feed_json("utterance_end", turn=T1, reason="vad")
    pcm = await asyncio.wait_for(task, 1)
    assert pcm is not None and len(pcm) == 2048
    await no_utterance(hub)  # в разговор не попала
    await eventually(lambda: [m["type"] for m in conn.sent_json()][-2:] == ["reply_start", "reply_end"])
    assert all(m.get("turn") == T1 for m in conn.sent_json())


async def test_record_without_speech_or_on_busy_is_none() -> None:
    hub = make_hub(FakeClock())
    conn = await v3(hub)
    task = asyncio.create_task(hub.record("A"))
    await eventually(lambda: bool(conn.sent_json()))
    conn.feed_json("utterance_end", turn=T1, reason="no_speech")
    assert await asyncio.wait_for(task, 1) is None
    await eventually(lambda: not hub.is_active("A", 1))
    task = asyncio.create_task(hub.record("A"))
    await eventually(lambda: len(conn.sent_json()) == 2)
    conn.feed_json("busy", turn=conn.sent_json()[-1]["turn"])
    assert await asyncio.wait_for(task, 1) is None


async def test_record_refused_when_busy_or_unknown_and_times_out() -> None:
    clock = FakeClock()
    hub = make_hub(clock)
    await accepted_turn(hub, clock, "A", protocol=3)
    assert await hub.record("A") is None  # идёт ход
    assert await hub.record("нет такой") is None
    conn = await v3(hub, "B")
    assert await hub.record("B", timeout_s=0.05) is None  # колонка молчит
    await eventually(lambda: [m["type"] for m in conn.sent_json()] == ["listen", "cancel_turn"])
