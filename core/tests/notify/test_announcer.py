"""Тесты очереди объявлений: доставка, повторы, срок, выбор колонки, порядок, слушание, остановка."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from announcer_helpers import RETRY_S, finished, setup, texts, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.notify import Announcer


async def test_delivered_once() -> None:
    port, sink, announcer = setup("kitchen")
    announcer.say("kitchen", "Готово.", "big")
    assert sink.events == []  # до итога событий нет
    await until(lambda: bool(finished(sink)))
    (event,) = finished(sink)
    assert isinstance(event.pop("at"), float)
    assert event == {
        "turn_id": "a1",
        "device_id": "kitchen",
        "device_name": "Кухня",
        "text": "",
        "annotations": [],
        "style": "normal",
        "answer": "Готово.",
        "status": "ok",
        "path": ["big"],
        "delegations": [],
        "origin": "core",
        "kind": "announcement",
    }
    await asyncio.sleep(RETRY_S * 3)
    assert texts(port) == ["Готово."]
    assert port.listens == []
    await announcer.aclose()


async def test_busy_then_delivered() -> None:
    port, sink, announcer = setup("kitchen", retry_s=0.05)
    port.deliveries = ["busy", "lost", "delivered"]
    started = asyncio.get_running_loop().time()
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    assert asyncio.get_running_loop().time() - started >= 0.1  # два повтора через retry_s
    assert [call.result for call in port.announces] == ["busy", "lost", "delivered"]
    assert finished(sink)[0]["status"] == "ok"
    await announcer.aclose()


async def test_interrupted_not_repeated() -> None:
    port, sink, announcer = setup("kitchen")
    port.deliveries = ["interrupted"]
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    await asyncio.sleep(RETRY_S * 3)
    assert len(port.announces) == 1
    assert finished(sink)[0]["status"] == "interrupted"
    await announcer.aclose()


async def test_expired() -> None:
    port, sink, announcer = setup("kitchen", expire_s=0.05)
    port.deliveries = ["lost"] * 1000
    announcer.say("kitchen", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    attempts = len(port.announces)
    assert attempts >= 2
    (event,) = finished(sink)
    assert (event["status"], event["device_id"], event["answer"]) == ("undelivered", "kitchen", "Готово.")
    await asyncio.sleep(RETRY_S * 3)
    assert len(port.announces) == attempts  # снято: больше не пробуем
    await announcer.aclose()


async def test_expired_without_device_names_requested_one() -> None:
    port, sink, announcer = setup(expire_s=0.03)
    announcer.say("hall", "Готово.", "big")
    await until(lambda: bool(finished(sink)))
    (event,) = finished(sink)
    assert (event["status"], event["device_id"], event["device_name"]) == ("undelivered", "hall", "Прихожая")
    assert port.announces == []
    await announcer.aclose()


async def test_fallback_to_last_active() -> None:
    port, sink, announcer = setup("kitchen")
    port.last_active = "kitchen"
    announcer.say("hall", "Готово.", "big")  # прихожая не подключена
    await until(lambda: bool(finished(sink)))
    assert [call.device_id for call in port.announces] == ["kitchen"]
    assert finished(sink)[0]["device_id"] == "kitchen"
    await announcer.aclose()


async def test_fallback_to_first_connected_proactive_device() -> None:
    # после старта ядра никто не говорил: последней активной нет — первая подключённая колонка v3
    port, sink, announcer = setup("kitchen", "hall")
    announcer.say("", "Таймер «чай»: время вышло.", "timers")
    await until(lambda: bool(finished(sink)))
    assert [call.device_id for call in port.announces] == ["kitchen"]  # по имени: «Кухня» раньше «Прихожей»
    assert finished(sink)[0]["status"] == "ok"
    await announcer.aclose()


async def test_last_active_wins_over_first_proactive() -> None:
    port, sink, announcer = setup("kitchen", "hall")
    port.last_active = "hall"
    announcer.say("", "Готово.", "timers")
    await until(lambda: bool(finished(sink)))
    assert [call.device_id for call in port.announces] == ["hall"]
    await announcer.aclose()


async def test_waits_for_any_device() -> None:
    port, sink, announcer = setup()
    announcer.say("kitchen", "Готово.", "big")
    await asyncio.sleep(RETRY_S * 5)
    assert port.announces == [] and sink.events == []  # колонок нет — ждём, не пробуя
    port.proactive.add("kitchen")
    await until(lambda: bool(finished(sink)))
    assert texts(port) == ["Готово."]
    assert finished(sink)[0]["status"] == "ok"
    await announcer.aclose()


async def test_order_per_device() -> None:
    port, sink, announcer = setup("kitchen")
    port.deliveries = ["busy", "delivered", "delivered"]
    announcer.say("kitchen", "Первое.", "big")
    announcer.say("kitchen", "Второе.", "big")
    await until(lambda: len(finished(sink)) == 2)
    assert texts(port) == ["Первое.", "Первое.", "Второе."]  # второе — только после итога первого
    assert [event["turn_id"] for event in finished(sink)] == ["a1", "a2"]
    await announcer.aclose()


async def test_one_delivery_per_device_when_falling_back() -> None:
    port, sink, announcer = setup("kitchen")
    port.last_active = "kitchen"
    announcer.say("kitchen", "Первое.", "big")
    announcer.say("hall", "Второе.", "big")  # тоже на кухню: ждёт итога первого, а не busy
    await until(lambda: len(finished(sink)) == 2)
    assert [call.result for call in port.announces] == ["delivered", "delivered"]
    await announcer.aclose()


@pytest.mark.parametrize(
    ("text", "listen_after", "listens"),
    [
        ("Какой город?", True, ["kitchen"]),
        ("Правда?» ", True, ["kitchen"]),
        ("Какой город?", False, []),
        ("Готово.", True, []),
    ],
)
async def test_question_opens_listen(text: str, listen_after: bool, listens: list[str]) -> None:
    port, sink, announcer = setup("kitchen")
    announcer.set_listen_after(listen_after)
    announcer.say("kitchen", text, "big")
    await until(lambda: bool(finished(sink)))
    assert port.listens == listens
    await announcer.aclose()


async def test_question_interrupted_does_not_listen() -> None:
    port, sink, announcer = setup("kitchen")
    port.deliveries = ["interrupted"]
    announcer.say("kitchen", "Какой город?", "big")
    await until(lambda: bool(finished(sink)))
    assert port.listens == []
    await announcer.aclose()


async def test_listen_failure_keeps_ok() -> None:
    port, sink, announcer = setup("kitchen")

    async def broken_listen(device_id: str) -> bool:
        raise ConnectionError("обрыв")

    port.listen = broken_listen
    announcer.say("kitchen", "Какой город?", "big")
    await until(lambda: bool(finished(sink)))
    assert finished(sink)[0]["status"] == "ok"  # объявление уже услышано
    await announcer.aclose()


async def test_aclose_cancels() -> None:
    port = FakeDevicePort()
    port.proactive = {"kitchen"}
    sink = RecordingSink()
    hold = asyncio.Event()
    state = {"started": False, "closed": False}

    async def endless(text: str) -> AsyncIterator[bytes]:
        state["started"] = True
        try:
            await hold.wait()
            yield text.encode()
        finally:
            state["closed"] = True

    announcer = Announcer(port, endless, events=sink, retry_s=RETRY_S)
    announcer.say("kitchen", "Первое.", "big")
    announcer.say("kitchen", "Второе.", "big")
    announcer.say("hall", "Третье.", "big")  # ждёт колонку
    await until(lambda: state["started"])
    await announcer.aclose()
    assert state["closed"]
    assert [t for t in asyncio.all_tasks() if t.get_name().startswith("announcer")] == []
    announcer.say("kitchen", "После.", "big")  # после остановки — не принимается
    await asyncio.sleep(RETRY_S * 3)
    assert sink.events == [] and port.announces == []
    assert [t for t in asyncio.all_tasks() if t.get_name().startswith("announcer")] == []
    await announcer.aclose()  # повторно — безопасно
