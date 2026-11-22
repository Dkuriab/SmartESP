"""Калибровка эха через API: POST /devices/{id}/echo/calibrate и PUT /devices/{id}/echo."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from smartesp.api import LogBuffer, create_api
from smartesp.contracts import EchoRefusedError
from smartesp.events import EventBus

from .conftest import HEADERS, PORT, TOKEN


class FakeEcho:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: EchoRefusedError | None = None

    async def calibrate_echo(self, device_id: str) -> None:
        self.calls.append(("calibrate", device_id))
        if self.error is not None:
            raise self.error

    async def set_echo_delay(self, device_id: str, delay_ms: int) -> None:
        self.calls.append(("delay", (device_id, delay_ms)))
        if self.error is not None:
            raise self.error


@pytest.fixture
def echo() -> FakeEcho:
    return FakeEcho()


@pytest.fixture
async def api(echo: FakeEcho) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    files, logs = FakeFilePlayback(), LogBuffer()
    app.include_router(
        create_api(FakeCore(), EventBus(), TOKEN, port=PORT, files=files, logs=logs, echo=echo)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client


async def test_calibrate_and_set_delay(api: httpx.AsyncClient, echo: FakeEcho) -> None:
    assert (await api.post("/api/v1/devices/aa:bb/echo/calibrate", headers=HEADERS)).status_code == 202
    put = await api.put("/api/v1/devices/aa:bb/echo", json={"delay_ms": 42}, headers=HEADERS)
    assert put.status_code == 202
    assert echo.calls == [("calibrate", "aa:bb"), ("delay", ("aa:bb", 42))]
    bad = await api.put("/api/v1/devices/aa:bb/echo", json={"delay_ms": 400}, headers=HEADERS)
    assert bad.status_code == 422


async def test_refusal_is_409_with_text(api: httpx.AsyncClient, echo: FakeEcho) -> None:
    echo.error = EchoRefusedError("колонка занята разговором")
    response = await api.post("/api/v1/devices/aa:bb/echo/calibrate", headers=HEADERS)
    assert (response.status_code, response.json()) == (409, {"detail": "колонка занята разговором"})


async def test_needs_token(api: httpx.AsyncClient, echo: FakeEcho) -> None:
    assert (await api.post("/api/v1/devices/aa:bb/echo/calibrate")).status_code == 401
    assert echo.calls == []
