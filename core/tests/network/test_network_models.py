"""Тесты сети исполнителей: id, модели участников, выгрузка и прогрев."""

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
