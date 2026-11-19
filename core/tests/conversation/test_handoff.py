"""Тесты оркестратора: передача задачи другому исполнителю посреди хода.

Сеть подделана исполнителем, который отдаёт куски так же, как ExecutorNetwork:
фраза входного, ReplyPart(handoff=…), затем куски цели. Интервалы — доли секунды.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from conversation_helpers import CountingTTS, Setup, make_utterance, running, until

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, Handoff, ReplyPart, ToolSpec

THINKING = ("kitchen", "thinking")
ERROR = ("kitchen", "error")
PHRASE = "Сейчас спрошу большую модель."
TASK = "Объясни, почему небо голубое"
HANDOFF = Handoff("dispatcher", "big", "Большая модель", TASK)


class FakeNetwork:
    """Как сеть исполнителей: куски входного, передача, затем (после delay) куски цели."""

    def __init__(
        self,
        before: Sequence[str],
        target: Sequence[str | ReplyPart],
        *,
        delay: float = 0.0,
        port: FakeDevicePort | None = None,
    ) -> None:
        self.id = "dispatcher"
        self._before = before
        self._target = target
        self._delay = delay
        self._port = port  # задан — ход прерывается (barge-in), пока ждём цель
        self.tts: CountingTTS | None = None
        self.spoken_at_target: list[str] | None = None  # что уже прозвучало, когда спросили цель
        self.closed = False

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        try:
            for text in self._before:
                yield ReplyPart(text)
            yield ReplyPart(handoff=HANDOFF)
            if self.tts is not None:
                self.spoken_at_target = list(self.tts.texts)
            if self._port is not None:
                self._port.deactivate("kitchen", 1)
            await asyncio.sleep(self._delay)
            for part in self._target:
                yield part if isinstance(part, ReplyPart) else ReplyPart(part)
        finally:
            self.closed = True


class StyledTTS(CountingTTS):
    """CountingTTS со стилями normal и quiet, запоминает стиль каждого вызова."""

    def __init__(self) -> None:
        super().__init__()
        self.used: list[str] = []

    def styles(self) -> list[str]:
        return ["normal", "quiet"]

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        self.used.append(style)
        return super().synthesize(text, style)


class OrderedPort(FakeDevicePort):
    """Порт, который запоминает, сколько ответов было проиграно к каждому сигналу."""

    def __init__(self) -> None:
        super().__init__(names={"kitchen": "Кухня"})
        self.plays_at_tone: list[tuple[str, int]] = []

    async def send_tone(self, device_id: str, name: str) -> None:
        self.plays_at_tone.append((name, len(self.plays)))
        await super().send_tone(device_id, name)


async def run_turn(setup: Setup, sink: RecordingSink) -> dict[str, object]:
    """Проводит ход 1 и возвращает данные turn_finished."""
    setup.port.feed(make_utterance())
    async with running(setup):
        await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
        await setup.port.wait_plays(1)
    return next(data for kind, data in sink.events if kind == "turn_finished")


async def test_phrase_sounds_before_target_answer() -> None:
    network = FakeNetwork([PHRASE], ["Потому что свет рассеивается. ", "Синий — сильнее всего."])
    sink = RecordingSink()
    setup = Setup(network, events=sink)
    network.tts = setup.tts
    finished = await run_turn(setup, sink)
    assert network.spoken_at_target == [PHRASE]
    assert setup.tts.texts == [PHRASE, "Потому что свет рассеивается.", "Синий — сильнее всего."]
    assert finished["status"] == "ok"
    assert finished["path"] == ["dispatcher", "big"]
    assert finished["delegations"] == [{"from": "dispatcher", "to": "big", "task": TASK, "auto": False}]
    assert setup.port.tones == []
    assert setup.port.plays[0].finished


async def test_history_keeps_question_and_all_spoken_answer() -> None:
    network = FakeNetwork([PHRASE], ["[style:quiet] Потому что свет рассеивается."])
    setup = Setup(network, tts=StyledTTS(), events=(sink := RecordingSink()))
    await run_turn(setup, sink)
    assert setup.history.messages() == [
        ChatMessage("user", "Какая погода?"),
        ChatMessage("assistant", f"{PHRASE} Потому что свет рассеивается."),
    ]


async def test_auto_handoff_is_marked() -> None:
    class AutoNetwork(FakeNetwork):
        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            yield ReplyPart(PHRASE)
            yield ReplyPart(
                handoff=Handoff("dispatcher", "big", "Большая модель", "Какая погода?", auto=True)
            )
            yield ReplyPart("Солнечно.")

    sink = RecordingSink()
    finished = await run_turn(Setup(AutoNetwork([], []), events=sink), sink)
    assert finished["delegations"] == [
        {"from": "dispatcher", "to": "big", "task": "Какая погода?", "auto": True}
    ]


async def test_thinking_tones_while_waiting_for_target() -> None:
    # цель отвечает через 0,25 с: «думаю» в 0,1 и 0,2 с от начала ожидания
    network = FakeNetwork([PHRASE], ["Ответ большой модели."], delay=0.25)
    sink = RecordingSink()
    setup = Setup(network, events=sink, thinking_interval_s=0.1, delegate_limit_s=5)
    finished = await run_turn(setup, sink)
    assert setup.port.tones == [THINKING, THINKING]
    assert finished["status"] == "ok"


async def test_target_limit_speaks_phrase_then_error_tone() -> None:
    # «думаю» в 0,05; 0,10; 0,15 с, в 0,175 с — «Не успела…», после звука — сигнал ошибки
    network = FakeNetwork([PHRASE], ["Поздно."], delay=10)
    port = OrderedPort()
    sink = RecordingSink()
    setup = Setup(network, events=sink, port=port, thinking_interval_s=0.05, delegate_limit_s=0.175)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Не успела ответить, спроси попозже."]
    assert port.tones == [THINKING, THINKING, THINKING, ERROR]
    assert port.plays_at_tone[-1] == ("error", 1)  # сигнал ошибки — после проигранного ответа
    assert finished["status"] == "error"
    assert network.closed
    assert setup.history.messages() == []


async def test_handoff_without_phrase_thinks_at_once() -> None:
    network = FakeNetwork([], ["Ответ большой модели."], delay=0.25)
    sink = RecordingSink()
    setup = Setup(network, events=sink, thinking_interval_s=0.1, delegate_limit_s=5)
    finished = await run_turn(setup, sink)
    assert setup.port.tones == [THINKING, THINKING, THINKING]  # сразу, в 0,1 и 0,2 с
    assert setup.tts.texts == ["Ответ большой модели."]
    assert finished["status"] == "ok"
    assert finished["answer"] == "Ответ большой модели."


async def test_failure_part_is_spoken_then_error_tone() -> None:
    network = FakeNetwork([PHRASE], [ReplyPart("Большая модель сейчас не отвечает.", failure=True)])
    port = OrderedPort()
    sink = RecordingSink()
    setup = Setup(network, events=sink, port=port)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Большая модель сейчас не отвечает."]
    assert port.plays_at_tone == [("error", 1)]
    assert finished["status"] == "error"
    assert finished["path"] == ["dispatcher", "big"]
    assert setup.history.messages() == []


async def test_target_style_tag_applies_and_is_hidden() -> None:
    tts = StyledTTS()
    network = FakeNetwork([PHRASE], ["[sty", "le:quiet] Тише, все спят уже давно. ", "Завтра солнечно."])
    sink = RecordingSink()
    finished = await run_turn(Setup(network, tts=tts, events=sink), sink)
    assert tts.used == ["normal", "quiet", "quiet"]
    assert tts.texts == [PHRASE, "Тише, все спят уже давно.", "Завтра солнечно."]
    assert finished["style"] == "quiet"
    assert finished["answer"] == f"{PHRASE} Тише, все спят уже давно. Завтра солнечно."


async def test_dispatcher_style_is_kept_for_target() -> None:
    tts = StyledTTS()
    network = FakeNetwork([f"[style:quiet] {PHRASE}"], ["[style:normal] Ответ большой модели."])
    sink = RecordingSink()
    finished = await run_turn(Setup(network, tts=tts, events=sink), sink)
    assert tts.used == ["quiet", "quiet"]
    assert tts.texts == [PHRASE, "Ответ большой модели."]
    assert finished["style"] == "quiet"


async def test_barge_in_while_waiting_for_target_closes_stream() -> None:
    # колонку перебили, пока цель думает: ждать предел (30 с) не нужно
    sink = RecordingSink()
    port = FakeDevicePort(names={"kitchen": "Кухня"})
    network = FakeNetwork([PHRASE], ["Поздно."], delay=30, port=port)
    setup = Setup(network, events=sink, port=port, thinking_interval_s=5, delegate_limit_s=30)
    finished = await run_turn(setup, sink)
    assert network.closed
    assert finished["status"] == "interrupted"
    assert setup.port.tones == []
    assert setup.history.messages() == []


async def test_turn_without_handoff_path_is_entry_id() -> None:
    class Plain(FakeExecutor):
        id = "dispatcher"

    sink = RecordingSink()
    finished = await run_turn(Setup(Plain(["Солнечно."]), events=sink), sink)
    assert finished["path"] == ["dispatcher"]
    assert finished["delegations"] == []


async def test_path_of_unidentified_executor_is_entry() -> None:
    sink = RecordingSink()
    finished = await run_turn(Setup(FakeExecutor(["Солнечно."]), events=sink), sink)
    assert finished["path"] == ["entry"]
