"""Жизнь ядра на подделках: старт в warming, прогрев в фоне, честная остановка, слежка за родителем."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import time
from pathlib import Path

import pytest
import uvicorn
from core_harness import (
    HEADERS,
    TOOLS_OLLAMA,
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
from smartesp.config import ExecutorConfig, SttConfig
from smartesp.contracts import Executor, ReplyPart, SpeechToText, Subscription, ToolCall
from smartesp.lifecycle import GracefulServer, RunFile, watch_parent
from smartesp.main import main
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
    answer = ["Раз. ", "Два. ", "Три."]
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


async def next_change(events: Subscription) -> dict[str, object]:
    """Данные следующего события change_applied."""
    async with asyncio.timeout(2):
        async for event in events:
            if event.kind == "change_applied":
                return event.data
    raise AssertionError("лента закрылась")


async def test_prompt_change_keeps_model_and_model_change_unloads_old(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    core = make_core(tmp_path, fake_kinds(ollama_factory(made)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    applied = core.bus.subscribe()

    await core.core.patch_config({"stages": []})
    assert (await next_change(applied))["ok"]
    # старт: made[0] — диспетчер, made[1] — big; правка stages: made[2], made[3]
    assert "[style:quiet]" in made[0].prompt and "[style:quiet]" in made[1].prompt
    assert "[style:quiet]" not in made[2].prompt and "[style:quiet]" not in made[3].prompt
    assert made[0].unloaded == [] and made[1].unloaded == []  # те же модели: выгружать нельзя
    await eventually(lambda: made[3].warmed == 1)  # big греется в фоне

    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "other"}]})
    change = await next_change(applied)
    assert change["ok"], change
    assert made[-1].model == "other" and made[-1].warmed == 1
    assert made[2].unloaded == [1.0] and made[3].unloaded == [1.0]  # обе модели ушли из сети
    await applied.aclose()
    await stop(core)
    assert made[-1].unloaded == [1.0]
    await finish(core)


async def test_stop_mid_release_unloads_old_and_new_models(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    answer = ["Раз. ", "Два. ", "Три."]
    core = make_core(tmp_path, fake_kinds(ollama_factory(made, answer, delay=0.15)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    speaking, _ = await connect(core, "kitchen")
    startup = core.live.executor
    ask(speaking, 1)
    await eventually(lambda: "reply_start" in sent_types(speaking))
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "other"}]})
    await eventually(lambda: len(made) == 3 and core.live.executor is not startup)  # старая ждёт хода
    assert made[0].unloaded == [] and made[1].unloaded == []

    await stop(core)
    assert made[0].unloaded == [1.0]  # старые модели выгружены один раз, хоть release и отменён
    assert made[1].unloaded == [1.0]
    assert made[2].model == "other" and made[2].unloaded == [1.0]
    await finish(core)


async def test_stop_mid_build_unloads_model_being_warmed(tmp_path: Path) -> None:
    made: list[FakeOllama] = []

    def factory(config: ExecutorConfig) -> Executor:
        gate = asyncio.Event() if config.model == "big" else None
        made.append(FakeOllama(["Да."], config.model, warm_gate=gate))
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "big"}]})
    await eventually(lambda: len(made) == 3)  # новая модель греется
    await stop(core)
    assert made[2].model == "big" and made[2].unloaded == [1.0]
    assert made[0].unloaded == [1.0] and made[1].unloaded == [1.0]
    await finish(core)


async def test_turn_with_handoff_goes_through_network(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    delegate = ToolCall("delegate", {"executor": "big", "task": "Объясни теорию относительности"})

    def factory(config: ExecutorConfig) -> Executor:
        parts = ["Сейчас спрошу большую модель. ", ReplyPart(tool_call=delegate)]
        if config.id == "big":
            parts = ["Это долгий рассказ про пространство и время."]
        made.append(FakeOllama(parts, config.model, prompt=config.system_prompt))
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory), ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: core.core.state == "ready")
    assert "delegate" in made[0].prompt and "Большая модель" in made[0].prompt
    speaking, _ = await connect(core, "kitchen")
    ask(speaking, 1)
    await eventually(lambda: "reply_end" in sent_types(speaking))
    big = made[2]  # диспетчер, его вариант без правила передачи, затем big
    assert len(big.calls) == 1 and "Задача от диспетчера" in big.calls[0][-1].content
    async with client(core) as http:
        await eventually(lambda: bool(core.core.turns(1)))
        turns = (await http.get("/api/v1/turns", headers=HEADERS)).json()
    assert turns[0]["path"] == ["dispatcher", "big"]
    assert turns[0]["delegations"][0]["to"] == "big"
    await stop(core)
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


async def test_run_file_holds_port_and_pid_and_is_removed(tmp_path: Path) -> None:
    run_file = RunFile(tmp_path / "run" / "core.json")
    run_file.write(8765)
    data = json.loads((tmp_path / "run" / "core.json").read_text())
    assert data["port"] == 8765 and data["pid"] == os.getpid()
    assert abs(data["started_at"] - time.time()) < 5
    run_file.remove()
    assert not (tmp_path / "run" / "core.json").exists()


def test_run_file_of_other_process_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "run" / "core.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"port": 1, "pid": os.getpid() + 1, "started_at": 0}))
    RunFile(path).remove()
    assert path.exists()


async def test_parent_watch_eof_stops_server_gracefully(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    ports: list[int] = []

    def started(port: int) -> None:
        ports.append(port)
        core.run_file.write(port)

    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=lambda: stop(core), on_started=started)
    read_fd, write_fd = os.pipe()
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    watch_parent(read_fd, server.request_stop)
    assert ports and ports[0] > 0
    assert (tmp_path / "run" / "core.json").exists()

    os.close(write_fd)  # родитель умер: stdin закрылся
    await asyncio.wait_for(serving, 5)
    os.close(read_fd)
    assert server.exit_requested
    assert core.core.state == "stopping"
    assert not (tmp_path / "run" / "core.json").exists()


async def test_second_stop_request_forces_exit(tmp_path: Path) -> None:
    hang = asyncio.Event()

    async def slow_stop() -> None:
        await hang.wait()

    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=slow_stop)
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    server.request_stop()
    await asyncio.sleep(0.05)
    assert not serving.done()
    server.request_stop()
    await asyncio.wait_for(serving, 5)
    assert server.force_exit
    await finish(core)


async def test_exit_request_during_restart_stop_cancels_restart(tmp_path: Path) -> None:
    hang = asyncio.Event()

    async def slow_stop() -> None:
        await hang.wait()

    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=slow_stop)
    restart = asyncio.Event()
    server.stop_after(restart.wait())
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    restart.set()  # перезапуск: идёт честная остановка
    await asyncio.sleep(0.05)
    assert not server.exit_requested
    server.request_stop()  # а тут SIGTERM от приложения
    await asyncio.wait_for(serving, 5)
    assert server.exit_requested
    await finish(core)


async def test_restart_alone_does_not_request_exit(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=lambda: stop(core))
    restart = asyncio.Event()
    server.stop_after(restart.wait())
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    restart.set()
    await asyncio.wait_for(serving, 5)
    assert not server.exit_requested


async def test_stop_is_bounded(tmp_path: Path) -> None:
    async def endless() -> None:
        await asyncio.Event().wait()

    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=endless, limit_s=0.1)
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    server.request_stop()
    await asyncio.wait_for(serving, 5)
    await finish(core)


def test_openapi_flag_writes_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTESP_HOME", str(tmp_path / "home"))
    path = tmp_path / "openapi.json"
    main(["--openapi", str(path)])
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert "/api/v1/status" in schema["paths"]
    assert not (tmp_path / "home").exists()  # ядро не стартовало: ни токена, ни журнала
