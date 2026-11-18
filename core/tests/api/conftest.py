from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from smartesp.api import create_api, mount_ui
from smartesp.events import EventBus

TOKEN = "secret-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def make_app(core: FakeCore, bus: EventBus, ui_dir: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(create_api(core, bus, TOKEN))
    mount_ui(app, ui_dir)
    return app


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def app(core: FakeCore, bus: EventBus, tmp_path: Path) -> FastAPI:
    return make_app(core, bus, tmp_path / "no-dist")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
