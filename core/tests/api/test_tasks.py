"""GET /api/v1/tasks: задачи «В работе» из реестра."""

from __future__ import annotations

import httpx

from fakes.fake_tasks import FakeTaskBoard
from smartesp.contracts import TaskInfo

from .conftest import HEADERS


def task(status: str = "running") -> TaskInfo:
    return TaskInfo(
        key="connector:timers/t1",
        source="connector:timers",
        id="t1",
        title="Картошка",
        status="running" if status == "running" else "done",
        started_at=1000.0,
        eta=1600.0,
        finished_at=None if status == "running" else 1600.0,
        device_id="",
        device_name="",
        person="Аня",
        result="",
    )


async def test_tasks_listed(client: httpx.AsyncClient, tasks: FakeTaskBoard) -> None:
    tasks.items = [task(), task("done")]
    response = await client.get("/api/v1/tasks", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert [t["status"] for t in body] == ["running", "done"]
    assert body[0]["key"] == "connector:timers/t1"
    assert body[0]["eta"] == 1600.0 and body[0]["person"] == "Аня"


async def test_tasks_need_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/tasks")).status_code == 401
