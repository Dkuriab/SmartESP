"""Тесты запоздавшего ответа: цель передачи не успела — «долго думает», ответ потом объявляется."""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
from conversation_helpers import TIMEOUT, Setup, make_utterance, running, until
from handoff_helpers import HANDOFF, PHRASE

from fakes.fake_announcer import FakeAnnouncer
from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, ExecutorError, ReplyPart, ToolSpec

LATER = "Большая модель долго думает. Скажу, когда будет готово."
TIMEOUT_PHRASE = "Не получилось ответить вовремя, спроси попозже."
ANNOUNCED = "Большая модель отвечает: Готово. Ответ сорок два."


class GatedNetwork:
    """Как сеть исполнителей: фраза входного, передача, затем куски цели — только после release()."""

    def __init__(self, target: Sequence[str | ReplyPart], error: Exception | None = None) -> None:
        self.id = "dispatcher"
        self._target = target
        self._error = error
        self._gate = asyncio.Event()
        self.closed = False

    def release(self) -> None:
        self._gate.set()

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        try:
            yield ReplyPart(PHRASE)
            yield ReplyPart(handoff=HANDOFF)
            await self._gate.wait()
            for part in self._target:
                yield part if isinstance(part, ReplyPart) else ReplyPart(part)
            if self._error is not None:
                raise self._error
        finally:
            self.closed = True


def late_setup(
    network: GatedNetwork, *, proactive: bool = True, late_limit_s: float = 600, part_idle_s: float = 20
) -> tuple[Setup, RecordingSink]:
    """Колонка v3 (или v2) и малые пределы ожидания цели."""
    sink = RecordingSink()
    setup = Setup(
        network,
        events=sink,
        thinking_interval_s=0.05,
        delegate_limit_s=0.1,
        late_limit_s=late_limit_s,
        part_idle_s=part_idle_s,
    )
    if proactive:
        setup.port.proactive.add("kitchen")
    return setup, sink


def finished(sink: RecordingSink, kind: str = "turn") -> list[dict[str, object]]:
    return [data for name, data in sink.events if name == "turn_finished" and data.get("kind") == kind]


async def wait_turn(setup: Setup, sink: RecordingSink) -> dict[str, object]:
    """Ждёт конца хода 1 (событие и проигранный звук)."""
    await until(lambda: bool(finished(sink)))
    await setup.port.wait_plays(1)
    return finished(sink)[0]


async def test_late_answer_announced() -> None:
    network = GatedNetwork(["Готово. ", "Ответ сорок два."])
    setup, sink = late_setup(network)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        turn = await wait_turn(setup, sink)
        assert turn["status"] == "ok"
        assert turn["answer"] == f"{PHRASE} {LATER}"
        assert " ".join(setup.tts.texts) == f"{PHRASE} {LATER}"
        assert not network.closed  # поток цели у фоновой задачи
        assert announcer.said == []
        network.release()
        await until(lambda: bool(announcer.said))
        await until(lambda: network.closed)
    assert announcer.said == [("kitchen", ANNOUNCED, "big")]
    assert setup.history.messages()[-1] == ChatMessage("assistant", ANNOUNCED)
    assert finished(sink, "announcement") == []  # о доставке сообщит очередь объявлений


async def test_late_disabled_keeps_timeout_phrase() -> None:
    network = GatedNetwork(["Поздно."])
    setup, sink = late_setup(network)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.orchestrator.set_speech(False, True)
    setup.port.feed(make_utterance())
    async with running(setup):
        turn = await wait_turn(setup, sink)
        await until(lambda: network.closed)
    assert turn["status"] == "error"
    assert turn["answer"] == f"{PHRASE} {TIMEOUT_PHRASE}"
    assert announcer.said == []


async def test_late_v2_device_keeps_timeout_phrase() -> None:
    network = GatedNetwork(["Поздно."])
    setup, sink = late_setup(network, proactive=False)
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.port.feed(make_utterance())
    async with running(setup):
        turn = await wait_turn(setup, sink)
        await until(lambda: network.closed)
    assert turn["status"] == "error"
    assert turn["answer"] == f"{PHRASE} {TIMEOUT_PHRASE}"


async def test_late_without_announcer_keeps_timeout_phrase() -> None:
    network = GatedNetwork(["Поздно."])
    setup, sink = late_setup(network)
    setup.port.feed(make_utterance())
    async with running(setup):
        turn = await wait_turn(setup, sink)
    assert turn["answer"] == f"{PHRASE} {TIMEOUT_PHRASE}"


async def test_late_pending_survives_setting_off() -> None:
    network = GatedNetwork(["Готово. Ответ сорок два."])
    setup, sink = late_setup(network)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        assert (await wait_turn(setup, sink))["answer"] == f"{PHRASE} {LATER}"
        setup.orchestrator.set_speech(False, True)  # обещанный ответ всё равно прозвучит
        network.release()
        await until(lambda: bool(announcer.said))
    assert announcer.said == [("kitchen", ANNOUNCED, "big")]


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ([], None),  # цель ничего не сказала
        (["[style:quiet] "], None),  # только метка стиля
        (["Готово."], ExecutorError("Ollama упала")),  # сбой посреди ответа
        ([ReplyPart("Большая модель сейчас не отвечает.", failure=True)], None),  # фраза сети об ошибке
    ],
)
async def test_late_target_fails_quietly(target: list[str | ReplyPart], error: Exception | None) -> None:
    network = GatedNetwork(target, error)
    setup, sink = late_setup(network)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        network.release()
        await until(lambda: bool(finished(sink, "announcement")))
        await until(lambda: network.closed)
    assert announcer.said == []
    (event,) = finished(sink, "announcement")
    assert event["status"] == "undelivered"
    assert event["origin"] == "core"
    assert event["path"] == ["big"]
    assert event["turn_id"] == "late1"
    assert event["device_id"] == "kitchen"


async def test_late_limit_from_turn_start() -> None:
    network = GatedNetwork(["Готово."])  # цель так и не ответит
    setup, sink = late_setup(network, late_limit_s=0.4)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        await until(lambda: bool(finished(sink, "announcement")))
        await until(lambda: network.closed)
    assert announcer.said == []
    assert finished(sink, "announcement")[0]["status"] == "undelivered"


async def test_late_idle_between_parts_fails() -> None:
    class Stalling(GatedNetwork):
        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            async for part in super().run(messages, tools):
                yield part
            await asyncio.sleep(10)  # первый кусок цели был, следующего нет дольше part_idle_s
            yield ReplyPart("Поздно.")

    network = Stalling(["Готово."])
    setup, sink = late_setup(network, part_idle_s=0.1)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        network.release()
        await until(lambda: bool(finished(sink, "announcement")))
    assert announcer.said == []


async def test_late_cancelled_on_drain() -> None:
    network = GatedNetwork(["Готово."])
    setup, sink = late_setup(network)
    announcer = FakeAnnouncer()
    setup.orchestrator.use_announcer(announcer)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        await setup.orchestrator.wait_turns(TIMEOUT)
        assert not network.closed
        await asyncio.wait_for(setup.orchestrator.drain(5), 0.5)  # не ждёт 5 с: отменяет сразу
        assert network.closed
        network.release()
        await asyncio.sleep(0.05)
    assert announcer.said == []
    assert finished(sink, "announcement") == []  # остановка ядра — не «не доставлено»


async def test_late_cancelled_when_run_stops() -> None:
    network = GatedNetwork(["Готово."])
    setup, sink = late_setup(network)
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
    assert network.closed


async def test_no_defer_after_stop_accepting() -> None:
    network = GatedNetwork(["Поздно."])
    setup, sink = late_setup(network)
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.port.feed(make_utterance())
    async with running(setup):
        await asyncio.sleep(0.02)  # ход уже ждёт цель
        setup.orchestrator.stop_accepting()
        turn = await wait_turn(setup, sink)
    assert turn["answer"] == f"{PHRASE} {TIMEOUT_PHRASE}"
