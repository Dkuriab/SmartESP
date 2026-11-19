"""Пересборка сети, когда меняется список инструментов коннекторов: пауза, ожидание старта, повторы."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from smartesp.lifecycle import ToolsRefresh

DEBOUNCE_S = 0.05
RETRY_S = 0.1


class Setup:
    """«Стартовая сеть стоит» и пересборка, которая может ждать или падать."""

    def __init__(self) -> None:
        self.ready = True
        self.builds = 0
        self.ok = 0
        self.gate: asyncio.Event | None = None  # задан — сборка ждёт его
        self.fail = False

    async def rebuild(self) -> None:
        self.builds += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("модель не прогрелась")
        self.ok += 1


@pytest.fixture
async def setup() -> AsyncIterator[tuple[Setup, ToolsRefresh]]:
    s = Setup()
    refresh = ToolsRefresh(lambda: s.ready, s.rebuild, debounce_s=DEBOUNCE_S, retry_s=RETRY_S)
    task = asyncio.create_task(refresh.run())
    yield s, refresh
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def wait_for(cond: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.005)


async def test_burst_of_changes_rebuilds_once(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    for _ in range(5):
        refresh.changed()
    await wait_for(lambda: s.ok == 1)
    await asyncio.sleep(DEBOUNCE_S * 4)
    assert s.builds == 1


async def test_waits_until_startup_network_is_live(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    s.ready = False
    refresh.changed()
    await asyncio.sleep(DEBOUNCE_S * 4)
    assert s.builds == 0  # сети ещё нет: строить нечего
    s.ready = True
    await wait_for(lambda: s.ok == 1)


async def test_change_during_rebuild_rebuilds_again(setup: tuple[Setup, ToolsRefresh]) -> None:
    s, refresh = setup
    s.gate = asyncio.Event()
    refresh.changed()
    await wait_for(lambda: s.builds == 1)
    refresh.changed()  # инструменты сменились, пока шла сборка
    s.gate.set()
    await wait_for(lambda: s.ok == 2)


async def test_failed_rebuild_is_retried_until_it_succeeds(
    setup: tuple[Setup, ToolsRefresh], caplog: pytest.LogCaptureFixture
) -> None:
    # (c) сбой не снимает смену: повтор после паузы, без новой смены инструментов
    s, refresh = setup
    s.fail = True
    refresh.changed()
    await wait_for(lambda: s.builds == 2)
    assert "не пересобрана" in caplog.text and s.ok == 0
    s.fail = False
    await wait_for(lambda: s.ok == 1)


def test_retry_delay_grows_to_cap() -> None:
    refresh = ToolsRefresh(lambda: True, Setup().rebuild)
    delays: list[float] = []
    for failures in range(1, 6):
        refresh._failures = failures  # pyright: ignore[reportPrivateUsage]
        delays.append(refresh.delay_s())
    assert delays == [15.0, 60.0, 240.0, 300.0, 300.0]
