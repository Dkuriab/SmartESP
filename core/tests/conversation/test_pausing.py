"""Звучащий ответ: не больше LOOKAHEAD_S секунд звука впереди услышанного, уступка, остаток по сроку."""

import asyncio

from conversation_helpers import make_utterance

from fakes.fake_device_port import FakeDevicePort
from smartesp.conversation.handoffs import Sentence
from smartesp.conversation.pausing import BYTES_PER_S, LOOKAHEAD_S, Pauses, SpokenReply
from smartesp.conversation.turn import Turn

AHEAD = int(LOOKAHEAD_S * BYTES_PER_S)


def reply(position: list[int | None]) -> SpokenReply:
    turn = Turn(make_utterance(), "Кухня", 0.0)
    return SpokenReply(turn, lambda: position[0], started_at=0.0)


async def test_next_sentence_waits_until_little_audio_is_ahead() -> None:
    position: list[int | None] = [0]
    spoken = reply(position)
    assert await spoken.admit(0, Sentence("Раз.", True), lambda: True)
    spoken.add_audio(AHEAD + BYTES_PER_S)  # впереди больше LOOKAHEAD_S
    spoken.end_sentence()
    waiting = asyncio.create_task(spoken.admit(1, Sentence("Два.", False), lambda: True))
    await asyncio.sleep(0.1)
    assert not waiting.done()
    position[0] = BYTES_PER_S  # прозвучала секунда — впереди ровно LOOKAHEAD_S
    assert await asyncio.wait_for(waiting, 1)


async def test_unknown_position_does_not_hold_sentences() -> None:
    spoken = reply([None])
    spoken.add_audio(10 * AHEAD)
    assert await asyncio.wait_for(spoken.admit(1, Sentence("Два.", False), lambda: True), 1)


async def test_request_while_waiting_yields_with_remainder() -> None:
    position: list[int | None] = [0]
    spoken = reply(position)
    spoken.add_audio(2 * AHEAD)
    waiting = asyncio.create_task(spoken.admit(1, Sentence("Два.", False), lambda: True))
    await asyncio.sleep(0.06)
    spoken.request()
    assert not await asyncio.wait_for(waiting, 1)
    assert spoken.paused and [s.text for s in spoken.remainder.sentences] == ["Два."]
    spoken.withdraw()  # уже уступил — просьбу не отозвать
    assert spoken.requested


async def test_first_sentence_always_spoken() -> None:
    spoken = reply([0])
    spoken.request()
    assert await spoken.admit(0, Sentence("Раз.", True), lambda: True)


async def test_remainder_expires_and_is_claimed_once() -> None:
    now = [100.0]
    pauses = Pauses(FakeDevicePort(), keep_s=300, clock=lambda: now[0])
    turn = Turn(make_utterance(), "Кухня", 0.0)
    spoken = pauses.start(turn)
    spoken.request()
    await spoken.admit(1, Sentence("Два.", False), lambda: True)
    pauses.stop(spoken)
    assert pauses.claim("kitchen") is not None
    assert pauses.claim("kitchen") is None  # забирает только один ход
    spoken = pauses.start(turn)
    spoken.request()
    await spoken.admit(1, Sentence("Два.", False), lambda: True)
    pauses.stop(spoken)
    now[0] += 301
    assert pauses.claim("kitchen") is None
