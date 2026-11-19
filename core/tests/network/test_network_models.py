"""Тесты сети исполнителей: id, модели участников, выгрузка и прогрев."""

import asyncio

import pytest

from fakes.fake_executor import FakeExecutor, FakeOllama
from smartesp.contracts import Identified, UsesModels, WarmsUp
from smartesp.network import ExecutorNetwork, Member, Target

BIG = Target("big", "Большая модель", "сложные вопросы")


def member(executor: FakeExecutor, name: str, targets: tuple[Target, ...] = ()) -> Member:
    return Member(executor, name, targets, True)


def network(entry: FakeExecutor) -> ExecutorNetwork:
    return ExecutorNetwork("dispatcher", {"dispatcher": member(entry, "Диспетчер", (BIG,))})


async def test_identified_with_entry_id() -> None:
    net = network(FakeExecutor([]))
    assert isinstance(net, Identified)
    assert net.id == "dispatcher"


async def test_models_union_and_unload_calls_members() -> None:
    gemma, deepseek = FakeOllama([], "gemma"), FakeOllama([], "deepseek")
    members = {"dispatcher": member(gemma, "Диспетчер", (BIG,)), "big": member(deepseek, "Большая модель")}
    net = ExecutorNetwork("dispatcher", members)
    assert isinstance(net, UsesModels)
    assert net.models() == {"gemma", "deepseek"}
    await net.unload_models(["deepseek", "other"], timeout_s=2.0)
    assert deepseek.unloaded == [2.0]
    assert gemma.unloaded == []


async def test_unload_shared_model_once() -> None:
    first, second = FakeOllama([], "gemma"), FakeOllama([], "gemma")
    members = {"dispatcher": member(first, "Диспетчер"), "big": member(second, "Большая модель")}
    await ExecutorNetwork("dispatcher", members).unload_models(["gemma"])
    assert len(first.unloaded) + len(second.unloaded) == 1


async def test_warm_up_warms_only_entry() -> None:
    gemma, deepseek = FakeOllama([], "gemma"), FakeOllama([], "deepseek")
    members = {"dispatcher": member(gemma, "Диспетчер", (BIG,)), "big": member(deepseek, "Большая модель")}
    net = ExecutorNetwork("dispatcher", members)
    assert isinstance(net, WarmsUp)
    await net.warm_up()
    assert (gemma.warmed, deepseek.warmed) == (1, 0)


def test_unknown_entry_is_rejected() -> None:
    with pytest.raises(ValueError):
        ExecutorNetwork("nobody", {})


async def test_warm_up_members_warms_others_concurrently_with_limit() -> None:
    gate = asyncio.Event()
    entry = FakeOllama([], "gemma")
    big, slow = FakeOllama([], "deepseek"), FakeOllama([], "qwen", warm_gate=gate)
    members = {
        "dispatcher": member(entry, "Диспетчер", (BIG,)),
        "big": member(big, "Большая модель"),
        "slow": member(slow, "Медленная"),
        "plain": member(FakeExecutor([]), "Без прогрева"),
    }
    result = await ExecutorNetwork("dispatcher", members).warm_up_members(timeout_s=0.05)
    assert result.keys() == {"big", "slow"}
    assert result["big"] is None
    assert result["slow"]
    assert (entry.warmed, big.warmed, slow.warmed) == (0, 1, 0)


async def test_warm_up_members_reports_errors_without_raising() -> None:
    class Broken(FakeOllama):
        async def warm_up(self) -> None:
            raise RuntimeError("модели нет")

    members = {"dispatcher": member(FakeOllama([], "gemma"), "Диспетчер"), "big": member(Broken([]), "Б")}
    result = await ExecutorNetwork("dispatcher", members).warm_up_members(timeout_s=1.0)
    assert result == {"big": "модели нет"}
