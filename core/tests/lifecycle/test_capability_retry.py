"""Повтор запроса возможностей моделей: Ollama поднялась позже ядра — сеть пересобирается с передачей."""

from __future__ import annotations

import asyncio
import logging

import pytest

from fakes.fake_executor import FakeOllama
from smartesp.contracts import Analyzer, Annotation, Executor, Utterance
from smartesp.lifecycle import Answering, CapabilityCache, CapabilityRetry, LiveAnswering
from smartesp.network import ExecutorNetwork, MemberSpec, build_network

SPECS = [
    MemberSpec("dispatcher", "Диспетчер", "", "small", "Промпт.", (("big", "сложное"),)),
    MemberSpec("big", "Большая модель", "", "big", "Промпт big."),
]


async def no_annotations(utterance: Utterance) -> list[Annotation]:
    return []


class Ollama:
    """Поддельный model_capabilities: пока up=False — сбой, потом — модели с инструментами."""

    def __init__(self) -> None:
        self.up = False
        self.calls: list[str] = []

    async def __call__(self, model: str) -> frozenset[str]:
        self.calls.append(model)
        if not self.up:
            raise ConnectionError("Ollama не запущена")
        return frozenset({"completion", "tools"})


class Setup:
    """Живая пара, кеш возможностей и пересборка сети тем же путём, что правка."""

    def __init__(self) -> None:
        self.ollama = Ollama()
        self.cache = CapabilityCache(self.ollama)
        self.live = LiveAnswering(self.install, self.wait_turns, turn_wait_s=5.0, unload_s=1.0)
        self.built: list[ExecutorNetwork] = []
        self.build_gate: asyncio.Event | None = None  # задан — сборка ждёт его
        self.fail_build = False

    def install(self, analyze: Analyzer, executor: Executor) -> None:
        pass

    async def wait_turns(self, timeout_s: float) -> None:
        pass

    async def rebuild(self) -> Answering:
        if self.fail_build:
            raise RuntimeError("модель не прогрелась")
        network = await build_network("dispatcher", SPECS, [], self.make, self.cache.get)
        self.built.append(network)
        if self.build_gate is not None:
            await self.build_gate.wait()
        analyze: Analyzer = no_annotations
        return await self.live.build((analyze, network), 5.0)

    def make(self, member_id: str, prompt: str) -> Executor:
        return FakeOllama([], next(s.model for s in SPECS if s.id == member_id), prompt=prompt)

    def retry(self, interval_s: float = 15.0) -> CapabilityRetry:
        return CapabilityRetry(self.live, self.cache.probe, self.rebuild, interval_s=interval_s)

    def network(self) -> ExecutorNetwork:
        assert isinstance(self.live.executor, ExecutorNetwork)
        return self.live.executor


async def started() -> Setup:
    """Ядро стартовало без Ollama: сеть собрана, возможности моделей неизвестны."""
    setup = Setup()
    setup.live.use(await setup.rebuild())
    assert setup.network().unknown_models() == frozenset({"small", "big"})
    assert not setup.network().members["dispatcher"].tools_ok
    return setup


async def test_no_rebuild_while_capabilities_stay_unknown() -> None:
    setup = await started()
    assert not await setup.retry().check()
    assert len(setup.built) == 1


async def test_rebuild_once_capabilities_become_known() -> None:
    setup = await started()
    first = setup.network()
    setup.ollama.up = True
    assert await setup.retry().check()
    network = setup.network()
    assert network is not first and network.unknown_models() == frozenset()
    assert network.members["dispatcher"].tools_ok and network.members["dispatcher"].targets
    assert not await setup.retry().check()  # всё известно — больше не пересобирает
    assert len(setup.built) == 2


async def test_capabilities_learned_elsewhere_still_rebuild() -> None:
    setup = await started()
    setup.ollama.up = True
    await setup.cache.get("small")  # например, интерфейс запросил список моделей
    assert await setup.retry().check()
    assert setup.network().members["dispatcher"].tools_ok


async def test_edit_applied_during_rebuild_wins() -> None:
    setup = await started()
    setup.ollama.up = True
    setup.build_gate = asyncio.Event()
    checking = asyncio.create_task(setup.retry().check())
    await asyncio.sleep(0.01)
    edit = FakeOllama([], "small")
    analyze: Analyzer = no_annotations
    setup.live.use((analyze, edit))  # правка настроек успела раньше
    setup.build_gate.set()
    assert not await checking
    assert setup.live.executor is edit


async def test_failed_rebuild_is_logged_and_tried_again(caplog: pytest.LogCaptureFixture) -> None:
    setup = await started()
    setup.ollama.up = True
    setup.fail_build = True
    with caplog.at_level(logging.WARNING):
        assert not await setup.retry().check()
    assert "Пересборка сети" in caplog.text
    setup.fail_build = False
    assert await setup.retry().check()


async def test_failed_rebuilds_back_off_and_warn_once(caplog: pytest.LogCaptureFixture) -> None:
    setup = await started()
    setup.ollama.up = True
    setup.fail_build = True
    retry = setup.retry()
    assert retry.delay_s() == 15.0
    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            assert not await retry.check()
    assert [r.levelno for r in caplog.records if "Пересборка" in r.message] == [
        logging.WARNING,
        logging.DEBUG,
        logging.DEBUG,
        logging.DEBUG,
    ]
    assert retry.delay_s() == 300.0  # 15 → 60 → 240 → 300 (потолок)


async def test_backoff_resets_when_live_pair_changes() -> None:
    setup = await started()
    setup.ollama.up = True
    setup.fail_build = True
    retry = setup.retry()
    assert not await retry.check()
    assert retry.delay_s() == 60.0
    analyze: Analyzer = no_annotations
    setup.live.use((analyze, FakeOllama([], "small")))  # правка настроек сменила пару
    assert retry.delay_s() == 15.0


async def test_backoff_resets_after_successful_rebuild() -> None:
    setup = await started()
    setup.ollama.up = True
    setup.fail_build = True
    retry = setup.retry()
    assert not await retry.check()
    setup.fail_build = False
    assert await retry.check()
    assert retry.delay_s() == 15.0


async def test_run_retries_every_interval_until_known() -> None:
    setup = await started()
    task = asyncio.create_task(setup.retry(interval_s=0.01).run())
    await asyncio.sleep(0.05)
    assert len(setup.built) == 1 and len(setup.ollama.calls) > 2  # спрашивает, но не пересобирает
    setup.ollama.up = True
    async with asyncio.timeout(1.0):
        while len(setup.built) < 2:
            await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup.network().members["dispatcher"].tools_ok


async def test_probe_failure_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    setup = Setup()
    with caplog.at_level(logging.INFO):
        assert await setup.cache.probe("small") == frozenset()
    assert caplog.records == []
