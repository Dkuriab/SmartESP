"""Жизнь процесса ядра: файл запуска, слежка за родителем, просьбы об остановке, схема API."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
import uvicorn
from core_harness import (
    eventually,
    fake_kinds,
    make_core,
    ollama_factory,
)

from smartesp.lifecycle import GracefulServer, RunFile, watch_parent
from smartesp.main import main
from smartesp.wiring import finish, stop


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
    server.request_stop()  # а тут SIGTERM от приложения: итог — выход, остановка не прерывается
    await asyncio.sleep(0.05)
    assert server.exit_requested and not server.force_exit and not serving.done()
    hang.set()
    await asyncio.wait_for(serving, 5)
    assert not server.force_exit
    await finish(core)


async def test_api_requests_during_stop_do_not_interrupt_it(tmp_path: Path) -> None:
    """Перезапуск и остановка из API во время остановки не ведут к аварийному выходу."""
    hang = asyncio.Event()
    stops: list[str] = []

    async def slow_stop() -> None:
        stops.append("stop")
        await hang.wait()

    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None)
    server = GracefulServer(config, stop=slow_stop)
    restart, stop_request = asyncio.Event(), asyncio.Event()
    server.stop_after(restart.wait())
    server.stop_after(stop_request.wait())
    serving = asyncio.create_task(server.serve())
    await eventually(lambda: server.started)
    restart.set()
    await asyncio.sleep(0.05)
    stop_request.set()
    await asyncio.sleep(0.05)
    assert not serving.done() and not server.force_exit
    hang.set()
    await asyncio.wait_for(serving, 5)
    assert stops == ["stop"] and not server.force_exit and not server.exit_requested
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
