import asyncio

import pytest

from fakes.fake_events import RecordingSink
from smartesp.events import EventBus


async def test_subscriber_gets_events_in_order():
    bus = EventBus(clock=lambda: 7.0)
    feed = bus.subscribe()
    bus.publish("wake", {"n": 1})
    bus.publish("wake", {"n": 2})
    first = await anext(feed)
    second = await anext(feed)
    assert (first.kind, first.data, first.at) == ("wake", {"n": 1}, 7.0)
    assert second.data == {"n": 2}


async def test_publish_never_blocks_and_drops_oldest():
    bus = EventBus(queue_size=10)
    feed = bus.subscribe()
    for n in range(15):
        bus.publish("wake", {"n": n})  # синхронный: не ждёт
    got = [(await anext(feed)).data["n"] for _ in range(10)]
    assert got == list(range(5, 15))


async def test_aclose_after_break_unsubscribes():
    bus = EventBus()
    feed = bus.subscribe()
    bus.publish("wake", {})
    async for _ in feed:
        break
    assert bus.subscriber_count == 1
    await feed.aclose()
    await feed.aclose()
    assert bus.subscriber_count == 0


async def test_aclose_of_never_started_subscription():
    bus = EventBus()
    feed = bus.subscribe()
    assert bus.subscriber_count == 1
    await feed.aclose()
    assert bus.subscriber_count == 0


async def test_cancelled_while_waiting_unsubscribes():
    bus = EventBus()

    async def reader() -> None:
        async for _ in bus.subscribe():
            pass

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    assert bus.subscriber_count == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert bus.subscriber_count == 0


def test_publish_copies_data():
    bus = EventBus()
    data: dict[str, object] = {"turn_id": 1}
    bus.publish("turn_finished", data)
    data["turn_id"] = 2
    assert bus.recent_turns(1) == [{"turn_id": 1}]


def test_invalid_sizes():
    with pytest.raises(ValueError):
        EventBus(queue_size=0)
    bus = EventBus()
    bus.publish("turn_finished", {"turn_id": 1})
    assert bus.recent_turns(0) == []
    assert bus.recent_turns(-1) == []


def test_recent_turns_keeps_last_100_newest_first():
    bus = EventBus()
    for n in range(1, 106):
        bus.publish("turn_finished", {"turn_id": n})
    bus.publish("wake", {"turn_id": 999})
    turns = bus.recent_turns(100)
    assert len(turns) == 100
    assert turns[0]["turn_id"] == 105
    assert [t["turn_id"] for t in bus.recent_turns(3)] == [105, 104, 103]


def test_publish_without_subscribers_is_fine():
    EventBus().publish("wake", {})


def test_recording_sink_records():
    sink = RecordingSink()
    sink.publish("wake", {"a": 1})
    assert sink.events == [("wake", {"a": 1})]
