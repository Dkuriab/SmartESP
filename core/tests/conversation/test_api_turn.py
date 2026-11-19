"""Тесты хода через API: вопрос текстом или голосом — тот же путь, ответ текстом, без звука."""

import asyncio
import time

import pytest
from conversation_helpers import CountingSTT, RecordingAnalyzer, Setup, make_utterance, running, until
from handoff_helpers import PHRASE, TASK, FakeNetwork

from fakes.fake_events import RecordingSink
from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.contracts import (
    Annotation,
    Answer,
    AskUnavailable,
    ChatMessage,
    ExecutorError,
    Question,
    ToolCall,
)
from smartesp.conversation import History, Orchestrator, asking
from smartesp.conversation.asking import BUSY, FAILED_PHRASE, LATE_PHRASE, NOT_HEARD

CHANNEL = "[канал] Telegram: вопрос не с колонки, ответ прочитают текстом"
VOICE = b"\x01\x00" * 1600


def telegram(text: str = "", pcm: bytes = b"") -> Question:
    """Вопрос от Ани из Telegram."""
    return Question(text=text, pcm=pcm, person="Аня", source="telegram")


def finished(sink: RecordingSink) -> dict[str, object]:
    return next(data for kind, data in sink.events if kind == "turn_finished")


async def test_text_question_answered_without_sound() -> None:
    sink, stt = RecordingSink(), CountingSTT()
    executor = FakeExecutor(["[style:quiet] Сегодня солнечно. ", "Тепло."])
    analyzer = RecordingAnalyzer([Annotation(text="сейчас 10:00", source="clock", label="время")])
    setup = Setup(executor, stt=stt, analyzer=analyzer, events=sink)
    answer = await setup.orchestrator.ask(telegram("Какая погода?"))
    assert answer == Answer("Сегодня солнечно. Тепло.", "api1")
    assert stt.calls == 0
    assert (setup.port.plays, setup.port.tones, setup.tts.texts) == ([], [], [])
    assert (analyzer.seen[0].text, analyzer.seen[0].origin) == ("Какая погода?", "api")
    content = f"[время] сейчас 10:00\n{CHANNEL}\n[человек] Аня\n\nКакая погода?"
    assert executor.calls[0][-1] == ChatMessage("user", content)  # без строки «Колонка: …»
    assert setup.history.messages() == [  # в истории видно, откуда вопрос
        ChatMessage("user", "[Telegram · Аня] Какая погода?"),
        ChatMessage("assistant", "Сегодня солнечно. Тепло."),
    ]
    kinds = [kind for kind, _ in sink.events]
    assert (kinds[0], kinds[-1], "turn_heard" in kinds) == ("turn_started", "turn_finished", False)
    data = finished(sink)
    expected = {"turn_id": "api1", "device_id": "api", "device_name": "Telegram", "origin": "api"}
    assert {key: data[key] for key in expected} == expected
    assert (data["source"], data["person"], data["status"]) == ("telegram", "Аня", "ok")
    assert data["text"] == "Какая погода?"
    assert data["answer"] == "Сегодня солнечно. Тепло."
    assert data["annotations"] == [{"source": "clock", "text": "сейчас 10:00"}]  # пометки канала — не в ленте


async def test_turn_ids_are_own_and_events_carry_them() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Да."]), events=sink)
    first = await setup.orchestrator.ask(Question(text="Раз"))
    second = await setup.orchestrator.ask(Question(text="Два"))
    assert (first.turn_id, second.turn_id) == ("api1", "api2")
    active = [data for kind, data in sink.events if kind == "executor_active"]
    assert active and {(data["turn_id"], data["device_id"]) for data in active} == {
        ("api1", "api"),
        ("api2", "api"),
    }
    assert finished(sink)["device_name"] == "Api"  # источник по умолчанию
    assert finished(sink)["person"] == ""


async def test_voice_question_goes_through_same_stt() -> None:
    sink, stt = RecordingSink(), CountingSTT("Который час?")
    executor = FakeExecutor(["Десять."])
    setup = Setup(executor, stt=stt, events=sink)
    answer = await setup.orchestrator.ask(telegram(pcm=VOICE))
    assert answer.text == "Десять."
    assert stt.calls == 1
    assert executor.calls[0][-1].content.endswith("\n\nКоторый час?")
    heard = next(data for kind, data in sink.events if kind == "turn_heard")
    assert (heard["turn_id"], heard["text"]) == ("api1", "Который час?")
    assert finished(sink)["text"] == "Который час?"


async def test_meaningless_voice_is_not_heard() -> None:
    sink, executor = RecordingSink(), FakeExecutor(["Не должно прозвучать."])
    setup = Setup(executor, stt=FakeSTT("Субтитры сделал DimaTorzok"), events=sink)
    answer = await setup.orchestrator.ask(telegram(pcm=VOICE))
    assert answer.text == NOT_HEARD
    assert executor.calls == []
    assert finished(sink)["status"] == "meaningless"
    assert setup.history.messages() == []


async def test_empty_voice_is_not_heard_without_stt() -> None:
    stt = CountingSTT()
    setup = Setup(FakeExecutor(["Нет."]), stt=stt)
    assert (await setup.orchestrator.ask(telegram())).text == NOT_HEARD
    assert stt.calls == 0


async def test_short_text_is_still_a_question() -> None:
    executor = FakeExecutor(["Записала."])
    setup = Setup(executor)
    assert (await setup.orchestrator.ask(Question(text="200"))).text == "Записала."
    assert len(executor.calls) == 1


async def test_not_ready_and_stopping_are_unavailable() -> None:
    history = History(max_turns=10, max_age_s=600)
    no_executor = Setup(None).orchestrator
    with pytest.raises(AskUnavailable, match="не готов"):
        await no_executor.ask(Question(text="Привет"))
    no_stt = Orchestrator(Setup(None).port, None, RecordingAnalyzer(), FakeExecutor(["Да."]), None, history)
    assert (await no_stt.ask(Question(text="Привет"))).text == "Да."  # тексту распознавание не нужно
    with pytest.raises(AskUnavailable, match="не готов"):
        await no_stt.ask(Question(pcm=VOICE))
    no_stt.stop_accepting()
    with pytest.raises(AskUnavailable, match="останавливается"):
        await no_stt.ask(Question(text="Привет"))


async def test_executor_failure_gets_honest_answer() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor([], error=ExecutorError("нет Ollama")), events=sink)
    assert (await setup.orchestrator.ask(Question(text="Привет"))).text == FAILED_PHRASE
    assert finished(sink)["status"] == "error"
    assert setup.history.messages() == []


async def test_empty_model_answer_is_failure() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["  "]), events=sink)
    assert (await setup.orchestrator.ask(Question(text="Привет"))).text == FAILED_PHRASE
    assert finished(sink)["status"] == "error"


async def test_delegation_answer_within_limit() -> None:
    sink = RecordingSink()
    network = FakeNetwork([PHRASE], ["Потому что свет рассеивается."])
    setup = Setup(network, events=sink)
    answer = await setup.orchestrator.ask(Question(text="Почему небо голубое?"))
    assert answer.text == f"{PHRASE} Потому что свет рассеивается."
    assert finished(sink)["path"] == ["dispatcher", "big"]
    assert setup.history.messages()[1] == ChatMessage(
        "assistant", PHRASE, tool_calls=(ToolCall("delegate", {"executor": "big", "task": TASK}),)
    )


async def test_slow_delegation_ends_with_honest_phrase_and_no_announcement() -> None:
    sink = RecordingSink()
    network = FakeNetwork([PHRASE], ["Слишком поздно."], delay=5.0)
    setup = Setup(network, events=sink, ask_limit_s=0.3, thinking_interval_s=0.05)
    started = time.monotonic()
    answer = await setup.orchestrator.ask(Question(text="Почему небо голубое?"))
    assert time.monotonic() - started < 2.0
    assert answer.text == f"{PHRASE} {LATE_PHRASE}"
    assert network.closed
    assert (setup.port.announces, setup.port.tones) == ([], [])
    assert finished(sink)["status"] == "error"
    assert setup.history.messages() == []


async def test_api_turn_runs_beside_speaker_turn() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Солнечно."], delay=0.05), events=sink)
    setup.port.feed(make_utterance())
    async with running(setup):
        answer = await setup.orchestrator.ask(telegram("Как дела?"))
        await setup.port.wait_plays(1)
        await until(lambda: len([k for k, _ in sink.events if k == "turn_finished"]) == 2)
    assert answer == Answer("Солнечно.", "api1")
    assert setup.port.plays[0].finished
    ids = {(data["device_id"], data["turn_id"]) for kind, data in sink.events if kind == "turn_finished"}
    assert ids == {("kitchen", 1), ("api", "api1")}


async def test_drain_cancels_api_turn() -> None:
    sink = RecordingSink()
    setup = Setup(FakeExecutor(["Долго."], delay=10.0), events=sink)
    asking = asyncio.create_task(setup.orchestrator.ask(Question(text="Привет")))
    await until(lambda: any(kind == "turn_started" for kind, _ in sink.events))
    setup.orchestrator.stop_accepting()
    await setup.orchestrator.drain(0.01)
    with pytest.raises(AskUnavailable, match="останавливается"):
        await asking
    assert finished(sink)["status"] == "interrupted"


async def test_cancelled_wait_cancels_api_turn() -> None:
    sink = RecordingSink()
    executor = FakeExecutor(["Долго."], delay=10.0)
    setup = Setup(executor, events=sink)
    asking = asyncio.create_task(setup.orchestrator.ask(Question(text="Привет")))
    await until(lambda: any(kind == "turn_started" for kind, _ in sink.events))
    asking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asking
    await until(lambda: any(kind == "turn_finished" for kind, _ in sink.events))
    assert executor.closed_early
    assert finished(sink)["status"] == "interrupted"


async def test_history_marks_source_without_person() -> None:
    setup = Setup(FakeExecutor(["Да."]))
    await setup.orchestrator.ask(Question(text="Привет", source="telegram"))
    await setup.orchestrator.ask(Question(text="Ещё"))
    users = [m.content for m in setup.history.messages() if m.role == "user"]
    assert users == ["[Telegram] Привет", "[Api] Ещё"]


async def test_at_most_two_api_turns_third_waits_then_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asking, "QUEUE_WAIT_S", 0.2)
    executor = FakeExecutor(["Долго."], delay=1.0)
    setup = Setup(executor)
    running_turns = [
        asyncio.create_task(setup.orchestrator.ask(Question(text=f"Вопрос {i}"))) for i in (1, 2)
    ]
    await until(lambda: len(executor.calls) == 2)
    with pytest.raises(AskUnavailable, match=BUSY):
        await setup.orchestrator.ask(Question(text="Третий"))
    assert len(executor.calls) == 2  # третий ход не начинался
    assert [(await t).text for t in running_turns] == ["Долго.", "Долго."]
    assert (await setup.orchestrator.ask(Question(text="Теперь можно"))).turn_id == "api3"


async def test_third_turn_runs_when_a_place_frees_and_waits_in_its_limit() -> None:
    sink = RecordingSink()
    executor = FakeExecutor(["Ответ."], delay=0.4)
    setup = Setup(executor, events=sink, ask_limit_s=0.6)
    answers = await asyncio.gather(*(setup.orchestrator.ask(Question(text=f"В{i}")) for i in (1, 2, 3)))
    assert [a.text for a in answers[:2]] == ["Ответ.", "Ответ."]
    assert answers[2].text == LATE_PHRASE  # ждал места ~0,4 с из своих 0,6 с — ответ не успел


async def test_stop_wakes_queued_question_without_a_turn() -> None:
    executor = FakeExecutor(["Долго."], delay=1.0)
    setup = Setup(executor)
    running_turns = [asyncio.create_task(setup.orchestrator.ask(Question(text=f"В{i}"))) for i in (1, 2)]
    await until(lambda: len(executor.calls) == 2)
    queued = asyncio.create_task(setup.orchestrator.ask(Question(text="Третий")))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    setup.orchestrator.stop_accepting()
    with pytest.raises(AskUnavailable, match="останавливается"):
        await queued
    assert time.monotonic() - started < 0.5  # не сидит свои 10 с
    await setup.orchestrator.drain(0.01)
    assert len(executor.calls) == 2  # после остановки ход не начинался
    for task in running_turns:
        with pytest.raises(AskUnavailable):
            await task


async def test_place_freed_by_drain_does_not_start_queued_turn() -> None:
    executor = FakeExecutor(["Долго."], delay=1.0)
    setup = Setup(executor)
    running_turns = [asyncio.create_task(setup.orchestrator.ask(Question(text=f"В{i}"))) for i in (1, 2)]
    await until(lambda: len(executor.calls) == 2)
    queued = asyncio.create_task(setup.orchestrator.ask(Question(text="Третий")))
    await asyncio.sleep(0.05)
    setup.orchestrator.stop_accepting()
    await setup.orchestrator.drain(0.01)
    results = await asyncio.gather(*running_turns, queued, return_exceptions=True)
    assert all(isinstance(result, AskUnavailable) for result in results)
    assert len(executor.calls) == 2


async def test_queued_question_uses_executor_swapped_while_waiting() -> None:
    old, new = FakeExecutor(["Старый."], delay=0.2), FakeExecutor(["Новый."])
    setup = Setup(old)
    running_turns = [asyncio.create_task(setup.orchestrator.ask(Question(text=f"В{i}"))) for i in (1, 2)]
    await until(lambda: len(old.calls) == 2)
    queued = asyncio.create_task(setup.orchestrator.ask(Question(text="Третий")))
    await asyncio.sleep(0.05)
    setup.orchestrator.use_executor(new)
    assert (await queued).text == "Новый."
    assert (len(old.calls), len(new.calls)) == (2, 1)
    assert [(await task).text for task in running_turns] == ["Старый.", "Старый."]
