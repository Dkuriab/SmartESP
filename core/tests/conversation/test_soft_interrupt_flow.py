"""Сквозной путь мягкого прерывания: настоящая очередь объявлений и оркестратор на поддельной колонке."""

import asyncio

from conversation_helpers import make_utterance, running, until
from pause_helpers import PIECES, sentences_of
from test_soft_interrupt import FOUR, ONE, THREE, TWO, finished, story_setup

from smartesp.notify import Announcer

RESUME = "Вернёмся к тому, о чём говорили?"


async def test_two_results_pause_story_then_yes_resumes_it() -> None:
    setup, port, sink = story_setup("Расскажи историю", "Да")
    announcer = Announcer(
        port, setup.orchestrator.speech, events=sink, interrupt=setup.orchestrator.interrupt, busy_poll_s=0.01
    )
    async with running(setup):
        port.feed(make_utterance(1))
        port.step()
        await until(lambda: len(port.taken) == 2)  # звучит середина первого предложения
        announcer.say("kitchen", "Таймер сработал.", "timers")
        announcer.say("kitchen", "Отчёт готов.", "claude")
        await asyncio.sleep(0.02)
        port.step(PIECES * 4)
        await port.wait_announces(2)
        assert sentences_of(port.plays[0].audio) == [1]  # первое предложение договорено, дальше — нет
        said = [call.audio for call in port.announces]
        assert len(said) == 2 and port.listens == ["kitchen"]
        port.gated = False
        port.feed(make_utterance(2))
        await until(lambda: len([t for t in finished(sink) if t["kind"] == "turn"]) == 2)
    turns = [t for t in finished(sink) if t["kind"] == "turn"]
    assert [t["interruption"] for t in turns] == ["paused", "resumed"]
    assert turns[1]["answer"] == f"{TWO} {THREE} {FOUR}"
    tts_texts: list[str] = setup.tts.texts  # type: ignore[attr-defined]
    assert tts_texts[0] == ONE
    assert "Кстати, готово: Таймер сработал." in tts_texts
    assert tts_texts[-4:] == [f"И ещё: Отчёт готов. {RESUME}", TWO, THREE, FOUR]
    await announcer.aclose()
