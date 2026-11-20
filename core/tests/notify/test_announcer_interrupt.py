"""Очередь объявлений и мягкое прерывание: «Кстати, готово», вопрос о продолжении, ожидание хода."""

import asyncio

from announcer_helpers import RETRY_S, finished, speak, texts, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.contracts import Interruption
from smartesp.notify import Announcer

RESUME = "Вернёмся к тому, о чём говорили?"


class Interrupter:
    """Мягкое прерывание-подделка: отвечает заданным итогом; paused/finished освобождают колонку."""

    def __init__(self, port: FakeDevicePort, result: Interruption) -> None:
        self.port = port
        self.result: Interruption = result
        self.calls: list[tuple[str, float]] = []

    async def __call__(self, device_id: str, since: float) -> Interruption:
        self.calls.append((device_id, since))
        if self.result != "none":
            self.port.busy.discard(device_id)
        return self.result


def setup(result: Interruption) -> tuple[FakeDevicePort, RecordingSink, Interrupter, Announcer]:
    port = FakeDevicePort({"kitchen": "Кухня"})
    port.proactive = {"kitchen"}
    sink = RecordingSink()
    interrupt = Interrupter(port, result)
    announcer = Announcer(port, speak, events=sink, retry_s=RETRY_S, interrupt=interrupt, busy_poll_s=0.01)
    return port, sink, interrupt, announcer


async def test_paused_reply_gets_prefix_and_resume_question_then_listen() -> None:
    port, sink, interrupt, announcer = setup("paused")
    port.busy = {"kitchen"}  # звучит ответ
    announcer.say("kitchen", "Большая модель отвечает: сорок два.", "big")
    await until(lambda: bool(finished(sink)))
    assert texts(port) == [f"Кстати, готово: Большая модель отвечает: сорок два. {RESUME}"]
    assert port.listens == ["kitchen"]  # кончили вопросом — колонка слушает
    assert interrupt.calls[0][0] == "kitchen"
    await announcer.aclose()


async def test_queue_of_two_results_asks_to_resume_once_at_the_end() -> None:
    port, sink, _, announcer = setup("paused")
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер «картошка» сработал.", "timers")
    announcer.say("kitchen", "Задача «отчёт» готова.", "claude")
    await until(lambda: len(finished(sink)) == 2)
    assert texts(port) == [
        "Кстати, готово: Таймер «картошка» сработал.",
        f"И ещё: Задача «отчёт» готова. {RESUME}",
    ]
    assert port.listens == ["kitchen"]
    announcer.say("kitchen", "Потом ещё одно.", "timers")  # колонка свободна — без приставок
    await until(lambda: len(finished(sink)) == 3)
    assert texts(port)[-1] == "Потом ещё одно."
    await announcer.aclose()


async def test_reply_finished_by_itself_gets_plain_text() -> None:
    port, sink, _, announcer = setup("finished")
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер сработал.", "timers")
    await until(lambda: bool(finished(sink)))
    assert texts(port) == ["Таймер сработал."]
    assert port.listens == []
    await announcer.aclose()


async def test_busy_turn_without_reply_waits_for_its_end() -> None:
    # человек говорит (или модель думает): прерывать нечего — ждём конца хода, без синтеза
    port, sink, interrupt, announcer = setup("none")
    port.busy = {"kitchen"}
    announcer.say("kitchen", "Таймер сработал.", "timers")
    await asyncio.sleep(0.1)
    assert port.announces == [] and len(interrupt.calls) > 1
    port.busy = set()
    await until(lambda: bool(finished(sink)))
    assert texts(port) == ["Таймер сработал."]
    await announcer.aclose()


async def test_failing_interrupt_falls_back_to_waiting() -> None:
    port = FakeDevicePort({"kitchen": "Кухня"})
    port.proactive, port.busy = {"kitchen"}, {"kitchen"}
    sink = RecordingSink()

    async def broken(device_id: str, since: float) -> Interruption:
        raise RuntimeError("сломалось")

    announcer = Announcer(port, speak, events=sink, retry_s=RETRY_S, interrupt=broken, busy_poll_s=0.01)
    announcer.say("kitchen", "Таймер сработал.", "timers")
    await asyncio.sleep(0.05)
    port.busy = set()
    await until(lambda: bool(finished(sink)))
    assert texts(port) == ["Таймер сработал."]
    await announcer.aclose()
