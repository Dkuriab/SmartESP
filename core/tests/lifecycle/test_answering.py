"""Живая пара (обработчики, исполнитель): подмена, освобождение и выгрузка моделей."""

from __future__ import annotations

import asyncio

import pytest

from fakes.fake_executor import FakeOllama
from smartesp.contracts import Analyzer, Annotation, Executor, ExecutorError, Utterance
from smartesp.lifecycle import Answering, LiveAnswering


async def no_annotations(utterance: Utterance) -> list[Annotation]:
    return []


def pair(executor: Executor) -> Answering:
    analyze: Analyzer = no_annotations
    return analyze, executor


class Setup:
    """LiveAnswering с записью подмен; during_wait вызывается, пока release ждёт ходы."""

    def __init__(self) -> None:
        self.installed: list[Executor] = []
        self.waits: list[float] = []
        self.during_wait: list[Answering] = []
        self.blocker: asyncio.Event | None = None  # задан — ожидание ходов висит до него
        self.live = LiveAnswering(self.install, self.wait_turns, turn_wait_s=5.0, unload_s=1.0)

    def install(self, analyze: Analyzer, executor: Executor) -> None:
        self.installed.append(executor)

    async def wait_turns(self, timeout_s: float) -> None:
        self.waits.append(timeout_s)
        if self.blocker is not None:
            await self.blocker.wait()
        for part in self.during_wait:
            self.live.use(part)


async def test_release_of_same_model_does_not_unload_or_wait() -> None:
    setup = Setup()
    old, new = FakeOllama([], "a"), FakeOllama([], "a")
    setup.live.use(pair(old))
    previous = setup.live.use(pair(new))
    assert previous is not None
    await setup.live.release(previous)
    assert old.unloaded == [] and setup.waits == []
    await setup.live.unload_all()
    assert new.unloaded == [1.0] and old.unloaded == []  # модель a выгружается один раз


async def test_release_of_other_model_waits_turns_then_unloads() -> None:
    setup = Setup()
    old, new = FakeOllama([], "a"), FakeOllama([], "b")
    setup.live.use(pair(old))
    previous = setup.live.use(pair(new))
    assert previous is not None
    await setup.live.release(previous)
    assert setup.waits == [5.0] and old.unloaded == [1.0]
    await setup.live.unload_all()
    assert old.unloaded == [1.0] and new.unloaded == [1.0]


async def test_release_rechecks_live_model_after_waiting() -> None:
    setup = Setup()
    old = FakeOllama([], "a")
    setup.live.use(pair(old))
    previous = setup.live.use(pair(FakeOllama([], "b")))
    setup.during_wait = [pair(FakeOllama([], "a"))]  # пока ждали, вернули модель a
    assert previous is not None
    await setup.live.release(previous)
    assert old.unloaded == []


async def test_cancelled_release_leaves_old_model_for_unload_all() -> None:
    setup = Setup()
    old, new = FakeOllama([], "a"), FakeOllama([], "b")
    setup.live.use(pair(old))
    previous = setup.live.use(pair(new))
    setup.blocker = asyncio.Event()
    assert previous is not None
    releasing = asyncio.create_task(setup.live.release(previous))
    await asyncio.sleep(0)
    releasing.cancel()
    await asyncio.gather(releasing, return_exceptions=True)
    setup.live.close()
    await setup.live.release(previous)  # после close — ничего не ждёт и не выгружает
    assert old.unloaded == []
    await setup.live.unload_all()
    assert old.unloaded == [1.0] and new.unloaded == [1.0]


async def test_failed_build_unloads_and_raises() -> None:
    class Failing(FakeOllama):
        async def warm_up(self) -> None:
            raise ExecutorError("не влезла в память")

    setup = Setup()
    executor = Failing([], "big")
    with pytest.raises(ExecutorError):
        await setup.live.build(pair(executor), 1.0)
    assert executor.unloaded == [1.0]
    await setup.live.unload_all()
    assert executor.unloaded == [1.0]


async def test_cancelled_build_is_unloaded_on_stop() -> None:
    setup = Setup()
    executor = FakeOllama([], "big", warm_gate=asyncio.Event())
    building = asyncio.create_task(setup.live.build(pair(executor), 10.0))
    await asyncio.sleep(0)
    building.cancel()
    await asyncio.gather(building, return_exceptions=True)
    await setup.live.unload_all()
    assert executor.unloaded == [1.0]


async def test_startup_pair_yields_to_newer_change() -> None:
    setup = Setup()
    gate = asyncio.Event()
    startup = FakeOllama([], "a", warm_gate=gate)
    warming = asyncio.create_task(setup.live.warm_startup(pair(startup), 10.0))
    await asyncio.sleep(0)
    changed = FakeOllama([], "b")
    setup.live.use(pair(changed))  # правку применили, пока старт грелся
    gate.set()
    await warming
    assert setup.live.executor is changed
    assert startup.unloaded == [1.0]


async def test_startup_pair_is_used_when_nothing_changed() -> None:
    setup = Setup()
    startup = FakeOllama([], "a")
    await setup.live.warm_startup(pair(startup), 10.0)
    assert setup.live.executor is startup and setup.installed == [startup] and startup.warmed == 1
