"""Жизнь ядра на подделках: старт в warming, прогрев в фоне, честная остановка."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from pathlib import Path

import pytest
from core_harness import (
    HEADERS,
    ask,
    client,
    connect,
    eventually,
    fake_kinds,
    make_core,
    ollama_factory,
    sent_types,
)

from fakes.fake_executor import FakeOllama
from smartesp import wiring
from smartesp.config import SttConfig
from smartesp.contracts import SpeechToText
from smartesp.wiring import finish, start, stop


async def test_status_is_warming_until_parts_are_warm(tmp_path: Path) -> None:
    gate = asyncio.Event()
    made: list[FakeOllama] = []
    core = make_core(tmp_path, fake_kinds(ollama_factory(made, warm_gate=gate)))
    start(core)
    async with client(core) as http:
        assert (await http.get("/api/v1/status", headers=HEADERS)).json()["state"] == "warming"
        gate.set()
        await eventually(lambda: core.core.state == "ready")
        status = (await http.get("/api/v1/status", headers=HEADERS)).json()
    assert status["state"] == "ready"
    assert status["voice"]["state"] == "ready"
    assert made[0].warmed == 1
    await stop(core)
    await finish(core)


async def test_wake_while_warming_gets_error_tone(tmp_path: Path) -> None:
    gate = asyncio.Event()
    core = make_core(tmp_path, fake_kinds(ollama_factory([], warm_gate=gate)))
    start(core)
    conn, _ = await connect(core, "kitchen")
    ask(conn, 1)
    await eventually(lambda: "reply_end" in sent_types(conn))
    assert {"type": "tone", "name": "error"} in conn.sent_json()
    assert core.core.state == "warming"
    gate.set()
    await stop(core)
    await finish(core)


async def test_hanging_executor_warm_up_does_not_block_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(wiring, "WARM_UP_TIMEOUT_S", 0.05)
    core = make_core(tmp_path, fake_kinds(ollama_factory([], warm_gate=asyncio.Event())))
    with caplog.at_level(logging.WARNING):
        start(core)
        await eventually(lambda: core.core.state == "ready")
    assert "не прогрелся" in caplog.text
    assert core.orchestrator.ready
    await stop(core)
    await finish(core)


async def test_graceful_stop_lets_reply_finish_and_cancels_new_wake(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    # первое предложение — целое (≥ 20 символов): страховка честности отдаёт его сразу
    answer = ["Раз, это первое предложение. ", "Два. ", "Три."]
    core = make_core(tmp_path, fake_kinds(ollama_factory(made, answer, delay=0.1)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    core.run_file.write(1234)
    speaking, _ = await connect(core, "kitchen")
    other, _ = await connect(core, "bedroom")
    ask(speaking, 1)
    await eventually(lambda: "reply_start" in sent_types(speaking))

    started = time.monotonic()
    stopping = asyncio.create_task(stop(core))
    await eventually(lambda: core.core.state == "stopping")
    other.feed_json("wake", turn=7, level=-30.0)
    await stopping
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert sent_types(speaking)[-1] == "reply_end"
    assert speaking.sent_audio()
    assert {"type": "cancel_turn", "turn": 7} in other.sent_json()
    assert speaking.closed and other.closed
    assert made[0].unloaded == [1.0]
    assert not (tmp_path / "run" / "core.json").exists()
    await finish(core)


async def test_warm_up_step_failure_is_logged_and_core_gets_ready(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(config: SttConfig) -> SpeechToText:
        raise RuntimeError("нет модели whisper")

    kinds = dataclasses.replace(fake_kinds(ollama_factory([])), stt={"mlx_whisper": broken})
    core = make_core(tmp_path, kinds)
    with caplog.at_level(logging.ERROR):
        start(core)
        await eventually(lambda: core.core.state == "ready")
    assert "STT не прогрелся" in caplog.text
    await stop(core)
    await finish(core)
