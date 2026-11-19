"""Тесты сети исполнителей: закрытие потоков и диалог, который получают участники."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from network_helpers import (
    QUESTION,
    call,
    collect,
    network,
)

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, ReplyPart, ToolCall


async def test_closing_mid_target_answer_closes_target_and_entry() -> None:
    entry = FakeExecutor(["Сейчас спрошу большую модель.", call()])
    big = FakeExecutor(["Первый.", "Второй.", "Третий."])
    stream = network(entry, big).run(QUESTION)
    seen: list[ReplyPart] = []
    async for part in stream:
        seen.append(part)
        if part.text == "Первый.":
            break
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()
    assert big.closed_early
    assert entry.closed_early  # поток входного закрыт сразу после вызова


async def test_cancel_while_target_waits_closes_target() -> None:
    entry = FakeExecutor([call()])
    big = FakeExecutor(["Долго."], delay=10)
    stream = network(entry, big).run(QUESTION)

    async def consume() -> None:
        async for _ in stream:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()
    assert big.closed_early


async def test_target_gets_flat_dialog_without_tool_structure() -> None:
    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Минутку.", tool_calls=(ToolCall("delegate", {"executor": "big"}),)),
        ChatMessage("tool", "Здравствуй", tool_name="delegate"),
        ChatMessage("user", "Сколько будет 17 в кубе?"),
    ]
    big = FakeExecutor(["4913."])
    await collect(network(FakeExecutor([call()]), big), history)
    assert big.calls[0][:2] == [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Минутку. Здравствуй"),
    ]
    assert all(not m.tool_calls and not m.tool_name and m.role != "tool" for m in big.calls[0])


async def test_entry_gets_structured_history_unchanged() -> None:
    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Минутку.", tool_calls=(ToolCall("delegate", {"executor": "big"}),)),
        ChatMessage("tool", "Здравствуй", tool_name="delegate"),
        ChatMessage("user", "Ещё вопрос"),
    ]
    entry = FakeExecutor(["Привет."])
    await collect(network(entry, FakeExecutor([])), history)
    assert entry.calls[0] == history


async def test_entry_without_targets_gets_flat_dialog() -> None:
    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Минутку.", tool_calls=(ToolCall("delegate", {"executor": "big"}),)),
        ChatMessage("tool", "Здравствуй", tool_name="delegate"),
        ChatMessage("user", "Ещё"),
    ]
    entry = FakeExecutor(["Привет."])
    await collect(network(entry, FakeExecutor([]), tools_ok=False), history)
    assert entry.calls[0] == [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Минутку. Здравствуй"),
        ChatMessage("user", "Ещё"),
    ]
