"""Тесты сети исполнителей: передача по вызову delegate, неверные вызовы, ошибки цели."""

import pytest
from network_helpers import (
    call,
    collect,
    handoffs,
    network,
    texts,
)

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, ExecutorError, Handoff, ReplyPart, ToolCall


async def test_entry_without_call_streams_its_text() -> None:
    entry = FakeExecutor(["При", "вет."])
    parts = await collect(network(entry, FakeExecutor([])))
    assert texts(parts) == ["При", "вет."]
    assert handoffs(parts) == []


async def test_entry_gets_delegate_tool_with_its_targets() -> None:
    entry = FakeExecutor(["Привет."])
    await collect(network(entry, FakeExecutor([])))
    (tool,) = entry.tools[0]
    assert tool.name == "delegate"
    props = tool.parameters["properties"]
    assert isinstance(props, dict)
    assert props["executor"]["enum"] == ["big"]


async def test_phrase_then_call_gives_text_handoff_and_target_parts() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Четыре тысячи", " девятьсот тринадцать."])
    parts = await collect(network(entry, big))
    assert parts == [
        ReplyPart("Сейчас спрошу большую модель."),
        ReplyPart(handoff=Handoff("dispatcher", "big", "Большая модель", "Посчитать 17 в кубе")),
        ReplyPart("Четыре тысячи"),
        ReplyPart(" девятьсот тринадцать."),
    ]


async def test_target_gets_messages_with_task_appended() -> None:
    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Здравствуй"),
        ChatMessage("user", "Сколько будет 17 в кубе?"),
    ]
    big = FakeExecutor(["4913."])
    await collect(network(FakeExecutor([call()]), big), history)
    assert big.calls[0] == [
        *history[:2],
        ChatMessage("user", "Сколько будет 17 в кубе?\n\nЗадача от диспетчера: Посчитать 17 в кубе"),
    ]
    assert history[-1].content == "Сколько будет 17 в кубе?"


async def test_target_without_own_targets_gets_no_tools() -> None:
    big = FakeExecutor(["4913."])
    await collect(network(FakeExecutor([call()]), big))
    assert big.tools == [()]


@pytest.mark.parametrize("bad", [call("nobody"), call(task="  "), call(task="")])
async def test_bad_call_gives_no_handoff(bad: ReplyPart, caplog: pytest.LogCaptureFixture) -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", bad])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert handoffs(parts) == []
    assert big.calls == []
    assert caplog.records and caplog.records[-1].levelname == "WARNING"


async def test_other_tool_call_passes_through() -> None:
    other = call(name="lamp")
    parts = await collect(network(FakeExecutor(["Включаю.", other]), FakeExecutor(["4913."])))
    assert parts == [ReplyPart("Включаю."), other]


async def test_call_with_non_string_arguments_is_ignored() -> None:
    bad = ReplyPart(tool_call=ToolCall("delegate", {"executor": 5, "task": None}))
    big = FakeExecutor(["4913."])
    parts = await collect(network(FakeExecutor([bad]), big))
    assert handoffs(parts) == []
    assert big.calls == []


async def test_valid_call_closes_source_right_away() -> None:
    entry = FakeExecutor(["Сейчас спрошу.", call(task="первая"), call(task="вторая"), "Лишний текст."])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert [h.task for h in handoffs(parts)] == ["первая"]
    assert texts(parts) == ["Сейчас спрошу.", "4913."]
    assert parts[1].handoff is not None  # передача сразу после вызова
    assert entry.closed_early  # остаток ответа не читался
    assert len(big.calls) == 1


async def test_bad_call_before_valid_one_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    entry = FakeExecutor([call("nobody", "первая"), call(task="вторая")])
    big = FakeExecutor(["4913."])
    parts = await collect(network(entry, big))
    assert [h.task for h in handoffs(parts)] == ["вторая"]
    assert any("nobody" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


async def test_target_error_becomes_failure_phrase() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Начало"], error=ExecutorError("нет модели"), error_after=1)
    parts = await collect(network(entry, big))
    assert parts[-1] == ReplyPart("Большая модель сейчас не отвечает.", failure=True)
    assert texts(parts) == [
        "Сейчас спрошу большую модель.",
        "Начало",
        "Большая модель сейчас не отвечает.",
    ]


@pytest.mark.parametrize("said", [[], [""], [" \n"], ["[style:quiet]"]])
async def test_silent_target_becomes_failure_phrase(said: list[str]) -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    parts = await collect(network(entry, FakeExecutor(said)))
    assert parts[-1] == ReplyPart("Большая модель сейчас не отвечает.", failure=True)


async def test_entry_error_propagates() -> None:
    entry = FakeExecutor([], error=ExecutorError("Ollama недоступна"))
    with pytest.raises(ExecutorError):
        await collect(network(entry, FakeExecutor([])))


async def test_any_target_exception_becomes_failure_phrase(caplog: pytest.LogCaptureFixture) -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Начало"], error=RuntimeError("сломалось"), error_after=1)
    parts = await collect(network(entry, big))
    assert parts[-1] == ReplyPart("Большая модель сейчас не отвечает.", failure=True)
    (record,) = [r for r in caplog.records if r.levelname == "WARNING"]
    assert record.exc_info is not None and isinstance(record.exc_info[1], RuntimeError)
