"""Тесты сети исполнителей: передача по фразе без вызова и модели без инструментов."""

import pytest
from network_helpers import (
    QUESTION,
    call,
    collect,
    handoffs,
    network,
    texts,
)

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, Handoff, ToolSpec


async def test_phrase_without_call_hands_off_automatically() -> None:
    entry = FakeExecutor(["Сейчас спрошу ", "большую модель."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == [
        Handoff("dispatcher", "big", "Большая модель", "Сколько будет 17 в кубе?", auto=True)
    ]
    assert texts(parts)[-1] == "4913."
    assert big.calls[0][-1].content.endswith("Задача от диспетчера: Сколько будет 17 в кубе?")


async def test_no_auto_handoff_after_bad_call() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call("nobody")])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == []


async def test_tools_not_ok_means_no_tool_and_no_auto_handoff() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big, tools_ok=False))
    assert entry.tools == [()]
    assert handoffs(parts) == []
    assert big.calls == []


async def test_tools_not_ok_drops_tools_passed_into_run() -> None:
    lamp = ToolSpec("lamp", "Включить свет.", {"type": "object", "properties": {}})
    entry = FakeExecutor(["Привет."])
    _ = [p async for p in network(entry, tools_ok=False).run(QUESTION, [lamp])]
    assert entry.tools == [()]


async def test_tools_passed_into_run_go_before_delegate() -> None:
    lamp = ToolSpec("lamp", "Включить свет.", {"type": "object", "properties": {}})
    entry = FakeExecutor(["Привет."])
    _ = [p async for p in network(entry, FakeExecutor([])).run(QUESTION, [lamp])]
    assert [t.name for t in entry.tools[0]] == ["lamp", "delegate"]


@pytest.mark.parametrize("answer", ["Это большая модель.", "Большая модель занята."])
async def test_answer_naming_target_without_asking_gives_no_handoff(answer: str) -> None:
    big = FakeExecutor(["4913."])
    parts = await collect(network(FakeExecutor([answer]), big))
    assert handoffs(parts) == []
    assert big.calls == []


async def test_auto_handoff_task_is_only_the_question() -> None:
    content = "[whisper] язык: ru\n[mood] спокойно\nКолонка: Кухня\n\nСколько будет 17 в кубе?"
    big = FakeExecutor(["4913."])
    parts = await collect(
        network(FakeExecutor(["Узнаю у большой модели."]), big), [ChatMessage("user", content)]
    )
    (handoff,) = handoffs(parts)
    assert handoff.task == "Сколько будет 17 в кубе?"
    assert big.calls[0][-1].content.endswith("Задача от диспетчера: Сколько будет 17 в кубе?")
