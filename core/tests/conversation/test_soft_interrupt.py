"""Мягкое прерывание: ответ уступает результату на границе предложения, «да» — продолжение."""

import asyncio
import time

from conversation_helpers import Setup, make_utterance, running, until
from pause_helpers import PIECES, PiecesTTS, SequenceSTT, SpeakingPort, sentences_of

from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage
from smartesp.conversation.pausing import agrees

ONE, TWO, THREE, FOUR = (
    "Жил-был кот по имени Барсик.",
    "Он любил спать на подоконнике.",
    "Однажды он увидел птицу.",
    "И с тех пор смотрит в окно.",
)
STORY = [f"{ONE} ", f"{TWO} ", f"{THREE} ", FOUR]


def story_setup(*texts: str) -> tuple[Setup, SpeakingPort, RecordingSink]:
    port, sink = SpeakingPort(), RecordingSink()
    setup = Setup(FakeExecutor(STORY), stt=SequenceSTT(*texts), tts=PiecesTTS(), events=sink, port=port)  # type: ignore[arg-type]
    return setup, port, sink


def finished(sink: RecordingSink) -> list[dict[str, object]]:
    return [data for kind, data in sink.events if kind == "turn_finished"]


async def pause_after_first_piece(setup: Setup, port: SpeakingPort) -> str:
    """Ход 1 звучит; после первого куска первого предложения приходит результат."""
    setup.port.feed(make_utterance(1))
    await until(lambda: len(port.taken) == 1)
    interrupting = asyncio.create_task(setup.orchestrator.interrupt("kitchen", time.monotonic()))
    await asyncio.sleep(0.01)
    port.step(PIECES * 4)  # колонка готова брать сколько угодно
    return await asyncio.wait_for(interrupting, 2)


async def test_reply_yields_at_sentence_boundary() -> None:
    setup, port, sink = story_setup("Расскажи историю")
    async with running(setup):
        result = await pause_after_first_piece(setup, port)
        await until(lambda: bool(finished(sink)))
    assert result == "paused"
    assert sentences_of(port.plays[0].audio) == [1]  # первое предложение целиком, дальше — ничего
    turn = finished(sink)[0]
    assert turn["interruption"] == "paused"
    assert turn["status"] == "interrupted"
    # в истории — только сказанное
    assert setup.history.messages()[-2:] == [
        ChatMessage("user", "Расскажи историю"),
        ChatMessage("assistant", ONE),
    ]


async def test_yes_continues_from_first_unspoken_sentence() -> None:
    setup, port, sink = story_setup("Расскажи историю", "Да, давай")
    async with running(setup):
        assert await pause_after_first_piece(setup, port) == "paused"
        port.gated = False
        port.feed(make_utterance(2))
        await until(lambda: len(finished(sink)) == 2)
    assert sentences_of(port.plays[1].audio) == [2, 3, 4]
    assert setup.tts.texts == [ONE, TWO, THREE, FOUR]  # type: ignore[attr-defined]
    resumed = finished(sink)[1]
    assert resumed["interruption"] == "resumed"
    assert resumed["status"] == "ok"
    assert resumed["answer"] == f"{TWO} {THREE} {FOUR}"
    assert setup.history.messages()[-1] == ChatMessage("assistant", f"{TWO} {THREE} {FOUR}")


async def test_other_reply_forgets_remainder() -> None:
    setup, port, sink = story_setup("Расскажи историю", "Какая погода?", "Да")
    async with running(setup):
        await pause_after_first_piece(setup, port)
        port.gated = False
        port.feed(make_utterance(2))
        await until(lambda: len(finished(sink)) == 2)
        port.feed(make_utterance(3))  # «да» уже ни к чему не относится — обычный ход
        await until(lambda: len(finished(sink)) == 3)
    assert [t["interruption"] for t in finished(sink)] == ["paused", None, None]


async def test_no_interruption_before_reply_or_for_reply_started_later() -> None:
    setup, port, _ = story_setup("Расскажи историю")
    since = time.monotonic()  # результат пришёл, пока человек говорил
    assert await setup.orchestrator.interrupt("kitchen", time.monotonic()) == "none"  # ответа нет
    async with running(setup):
        setup.port.feed(make_utterance(1))
        await until(lambda: len(port.taken) == 1)
        assert await setup.orchestrator.interrupt("kitchen", since) == "none"  # ответ начат позже
        port.step(PIECES * 4)
        await setup.port.wait_plays(1)
    assert sentences_of(port.plays[0].audio) == [1, 2, 3, 4]


async def test_reply_finishing_by_itself_is_finished() -> None:
    setup, port, _ = story_setup("Расскажи историю")
    setup.orchestrator.use_executor(FakeExecutor(["Коротко и ясно, без продолжения."]))
    async with running(setup):
        setup.port.feed(make_utterance(1))
        await until(lambda: len(port.taken) == 1)
        interrupting = asyncio.create_task(setup.orchestrator.interrupt("kitchen", time.monotonic()))
        port.step(PIECES)
        assert await asyncio.wait_for(interrupting, 2) == "finished"


def test_agrees() -> None:
    for text in ("Да.", "давай", "Да, продолжай", "Ага", "Конечно!", "Вернёмся"):
        assert agrees(text), text
    for text in ("Нет", "не надо", "Да нет", "Какая погода завтра в Москве будет?", "", "Потом"):
        assert not agrees(text), text
