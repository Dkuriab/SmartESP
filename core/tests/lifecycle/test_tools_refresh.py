"""Пересборка сети, когда меняется список инструментов коннекторов: не чаще раза в паузу."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from fakes.fake_executor import FakeOllama
from smartesp.contracts import Analyzer, Annotation, Executor, Utterance
from smartesp.lifecycle import Answering, LiveAnswering, ToolsRefresh

DEBOUNCE_S = 0.05


async def no_annotations(utterance: Utterance) -> list[Annotation]:
    return []


class Setup:
    """Живая пара и сборка новой по «текущим» инструментам."""

    def __init__(self) -> None:
        self.live = LiveAnswering(self.install, self.wait_turns, turn_wait_s=1.0, unload_s=1.0)
        self.builds = 0
        self.gate: asyncio.Event | None = None  # задан — сборка ждёт его
        self.fail = False

    def install(self, analyze: Analyzer, executor: Executor) -> None:
        pass

    async def wait_turns(self, timeout_s: float) -> None:
        pass

    async def build(self) -> Answering:
        self.builds += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("модель не прогрелась")
        return no_annotations, FakeOllama(["да"], "m")


@pytest.fixture
async def setup() -> AsyncIterator[tuple[Setup, ToolsRefresh]]:
    s = Setup()
    refresh = ToolsRefresh(s.live, s.build, debounce_s=DEBOUNCE_S)
    task = asyncio.create_task(refresh.run())
    yield s, refresh
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def wait_for(cond: object, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not cond():  # type: ignore[operator]
            await asyncio.sleep(0.005)


async def test_burst_of_changes_rebuilds_once(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    s.live.use(await s.build())
    s.builds = 0
    first = s.live.executor
    for _ in range(5):
        refresh.changed()
    await wait_for(lambda: s.live.executor is not first)
    await asyncio.sleep(DEBOUNCE_S * 4)
    assert s.builds == 1


async def test_waits_until_startup_network_is_live(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    refresh.changed()
    await asyncio.sleep(DEBOUNCE_S * 4)
    assert s.builds == 0  # сети ещё нет: строить нечего
    s.live.use(await s.build())
    first = s.live.executor
    await wait_for(lambda: s.live.executor is not first)


async def test_change_during_rebuild_rebuilds_again(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    s.live.use(await s.build())
    s.builds = 0
    s.gate = asyncio.Event()
    refresh.changed()
    await wait_for(lambda: s.builds == 1)
    refresh.changed()  # инструменты сменились, пока шла сборка
    s.gate.set()
    await wait_for(lambda: s.builds == 2)


async def test_failed_rebuild_is_logged_and_loop_survives(
    setup: tuple[Setup, ToolsRefresh], caplog: pytest.LogCaptureFixture
) -> None:
    s, refresh = setup
    s.live.use(await s.build())
    first = s.live.executor
    s.fail = True
    refresh.changed()
    await wait_for(lambda: "не пересобрана" in caplog.text)
    assert s.live.executor is first
    s.fail = False
    refresh.changed()
    await wait_for(lambda: s.live.executor is not first)
