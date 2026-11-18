"""Тесты запуска обработчиков."""

import asyncio
import logging
import time

import pytest

from smartesp.contracts import Annotation, Stage, Utterance
from smartesp.stages import run_stages

UTT = Utterance(device_id="d", turn=1, pcm=b"", started_at=0.0, text="привет")


class FakeStage:
    def __init__(self, name: str, delay: float = 0.0, fail: bool = False) -> None:
        self.name = name
        self._delay = delay
        self._fail = fail
        self.cancelled = False

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self._fail:
            raise RuntimeError("сбой")
        return [Annotation(text=self.name, source=self.name)]


async def test_runs_in_parallel_and_keeps_order() -> None:
    a, b = FakeStage("a", 0.3), FakeStage("b", 0.3)
    start = time.monotonic()
    out = await run_stages([(a, 1.0), (b, 1.0)], UTT)
    assert time.monotonic() - start < 0.5  # по очереди было бы ≥ 0,6 с
    assert [x.source for x in out] == ["a", "b"]


async def test_slow_stage_skipped_and_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    slow, ok = FakeStage("slow", 1.0), FakeStage("ok")
    with caplog.at_level(logging.WARNING):
        out = await run_stages([(slow, 0.05), (ok, 1.0)], UTT)
    assert [x.source for x in out] == ["ok"]
    assert slow.cancelled
    assert "slow" in caplog.text


async def test_failing_stage_skipped(caplog: pytest.LogCaptureFixture) -> None:
    bad, ok = FakeStage("bad", fail=True), FakeStage("ok")
    stages: list[tuple[Stage, float]] = [(bad, 1.0), (ok, 1.0)]
    with caplog.at_level(logging.WARNING):
        out = await run_stages(stages, UTT)
    assert [x.source for x in out] == ["ok"]
    assert "bad" in caplog.text
