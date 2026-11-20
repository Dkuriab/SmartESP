"""Задачи «В работе» для ядра: запуск, конец с итогом, ошибка, отмена."""

from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

from claude_tasks_mcp.server import build_server
from claude_tasks_mcp.settings import DEFAULT_TOOLS, Settings
from tests.conftest import FakeClock, FakeRunner, Session, connect


def server(
    data_dir: Path, runner: FakeRunner, clock: FakeClock, folders: tuple[tuple[str, Path], ...]
) -> MCPServer[Any]:
    settings = Settings(folders=folders, tools=DEFAULT_TOOLS, timeout_s=1800, claude_bin="")
    return build_server(settings, data_dir, runner=runner, now=clock)


async def wait_tasks(s: Session, count: int) -> None:
    with anyio.fail_after(5):
        while len(s.tasks) < count:
            await anyio.sleep(0.001)


async def test_task_reported_running_then_done_with_summary(
    data_dir: Path, runner: FakeRunner, clock: FakeClock, folders: tuple[tuple[str, Path], ...]
) -> None:
    async with connect(server(data_dir, runner, clock, folders)) as s:
        await s.call("task_start", person="Аня", task="почини тесты")
        await runner.started(1)
        await wait_tasks(s, 1)
        started = s.tasks[0]
        assert (started["type"], started["title"], started["status"], started["person"]) == (
            "task",
            "почини тесты",
            "running",
            "Аня",
        )
        runner.finish(0, True, "Починила тест. Всё зелёное.")
        await s.announce()
        await wait_tasks(s, 2)
        done = s.tasks[1]
        assert (done["id"], done["status"]) == (started["id"], "done")
        assert done["result"].startswith("Починила тест.")


async def test_failed_and_cancelled_tasks_reported(
    data_dir: Path, runner: FakeRunner, clock: FakeClock, folders: tuple[tuple[str, Path], ...]
) -> None:
    async with connect(server(data_dir, runner, clock, folders)) as s:
        await s.call("task_start", task="отчёт")
        await s.call("task_start", task="рефакторинг")
        await runner.started(2)
        runner.finish(0, False, "нет доступа")
        await s.announce()
        await s.call("task_cancel", name="рефакторинг")
        await wait_tasks(s, 4)
        assert [(t["title"], t["status"]) for t in s.tasks] == [
            ("отчёт", "running"),
            ("рефакторинг", "running"),
            ("отчёт", "failed"),
            ("рефакторинг", "cancelled"),
        ]
        assert s.tasks[2]["result"] == "нет доступа"
