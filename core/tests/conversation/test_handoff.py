"""Тесты оркестратора: передача задачи другому исполнителю посреди хода — фраза, ответ цели, путь, стиль."""

import asyncio
from collections.abc import AsyncIterator, Sequence

from conversation_helpers import Setup
from handoff_helpers import PHRASE, TASK, THINKING, FakeNetwork, StyledTTS, run_turn

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, Handoff, ReplyPart, ToolCall, ToolSpec


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
        ChatMessage(
            "assistant", PHRASE, tool_calls=(ToolCall("delegate", {"executor": "big", "task": TASK}),)
        ),
        ChatMessage("tool", "Потому что свет рассеивается.", tool_name="delegate"),
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
    async with asyncio.timeout(2):
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
