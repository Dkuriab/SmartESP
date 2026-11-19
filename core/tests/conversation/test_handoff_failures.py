"""Тесты оркестратора: цель передачи не успела, молчит или недоступна — звучит фраза, ход — ошибка."""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
from conversation_helpers import Setup
from handoff_helpers import CANNED, HANDOFF, PHRASE, SILENT, THINKING, FakeNetwork, run_turn

from fakes.fake_events import RecordingSink
from smartesp.contracts import ChatMessage, ReplyPart, ToolSpec


async def test_target_limit_speaks_phrase_instead_of_error_tone() -> None:
    # «думаю» в 0,05; 0,10; 0,15 с, в 0,175 с — «Не получилось ответить вовремя…»; фраза и есть сигнал ошибки
    network = FakeNetwork([PHRASE], ["Поздно."], delay=10)
    sink = RecordingSink()
    setup = Setup(network, events=sink, thinking_interval_s=0.05, delegate_limit_s=0.175)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Не получилось ответить вовремя, спроси попозже."]
    assert setup.port.tones == [THINKING, THINKING, THINKING]
    assert finished["status"] == "error"
    assert network.closed
    assert setup.history.messages() == []


async def test_failure_part_is_spoken_instead_of_error_tone() -> None:
    network = FakeNetwork([PHRASE], [ReplyPart(SILENT, failure=True)])
    sink = RecordingSink()
    setup = Setup(network, events=sink)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, SILENT]
    assert setup.port.tones == []
    assert finished["status"] == "error"
    assert finished["path"] == ["dispatcher", "big"]
    assert setup.history.messages() == []


@pytest.mark.parametrize("target", [[], [""], ["  "], ["[style:quiet]"]])
async def test_silent_target_speaks_phrase(target: list[str]) -> None:
    sink = RecordingSink()
    finished = await run_turn(Setup(FakeNetwork([PHRASE], target), events=sink), sink)
    assert finished["status"] == "error"
    assert finished["answer"] == f"{PHRASE} {SILENT}"


async def test_silent_call_to_unavailable_target_speaks_canned_and_failure() -> None:
    sink = RecordingSink()
    setup = Setup(FakeNetwork([], []), events=sink)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [CANNED, SILENT]
    assert setup.port.tones == []
    assert finished["status"] == "error"
    assert finished["answer"] == f"{CANNED} {SILENT}"
    assert setup.history.messages() == []


async def test_target_idle_before_any_text_speaks_phrase() -> None:
    class StallingTarget(FakeNetwork):
        async def run(
            self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
        ) -> AsyncIterator[ReplyPart]:
            yield ReplyPart(PHRASE)
            yield ReplyPart(handoff=HANDOFF)
            yield ReplyPart("[style:quiet] ")
            await asyncio.sleep(10)
            yield ReplyPart("Поздно.")

    sink = RecordingSink()
    setup = Setup(StallingTarget([], []), events=sink, part_idle_s=0.1)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, SILENT]
    assert finished["status"] == "error"
    assert setup.port.tones == []
    assert setup.history.messages() == []


async def test_failure_phrase_starts_new_sentence() -> None:
    # недоговорённый текст цели не склеивается с фразой об ошибке
    network = FakeNetwork([PHRASE], ["Потому что свет", ReplyPart(SILENT, failure=True)])
    sink = RecordingSink()
    setup = Setup(network, events=sink)
    finished = await run_turn(setup, sink)
    assert setup.tts.texts == [PHRASE, "Потому что свет", SILENT]
    assert finished["answer"] == f"{PHRASE} Потому что свет {SILENT}"
    assert finished["status"] == "error"
