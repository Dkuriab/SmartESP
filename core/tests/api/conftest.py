from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from fakes.fake_tasks import FakeTaskBoard
from smartesp.api import BodyLimit, LogBuffer, create_api, mount_ui
from smartesp.events import EventBus

TOKEN = "secret-token"
PORT = 8765
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def make_app(
    core: FakeCore,
    bus: EventBus,
    ui_dir: Path,
    files: FakeFilePlayback | None = None,
    logs: LogBuffer | None = None,
    tasks: FakeTaskBoard | None = None,
) -> FastAPI:
    app = FastAPI()
    files, logs = files or FakeFilePlayback(), logs or LogBuffer()
    api = create_api(core, bus, TOKEN, port=PORT, files=files, logs=logs, tasks=tasks or FakeTaskBoard())
    app.include_router(api)
    app.add_middleware(BodyLimit, token=TOKEN)
    mount_ui(app, ui_dir)
    return app


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def files() -> FakeFilePlayback:
    return FakeFilePlayback()


@pytest.fixture
def logs() -> LogBuffer:
    return LogBuffer(recent=5, queue_size=10)


@pytest.fixture
def tasks() -> FakeTaskBoard:
    return FakeTaskBoard()


@pytest.fixture
def app(
    core: FakeCore,
    bus: EventBus,
    files: FakeFilePlayback,
    logs: LogBuffer,
    tasks: FakeTaskBoard,
    tmp_path: Path,
) -> FastAPI:
    return make_app(core, bus, tmp_path / "no-dist", files, logs, tasks)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
