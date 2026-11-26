"""Потоки через API: /streams, /streams/control, /streams/volume и ссылка колонки /device/stream."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from fakes.fake_streams import FakeSpeakerStreams
from smartesp.api import LogBuffer, add_device_streams, create_api
from smartesp.contracts import StreamItem, StreamRefusal, StreamRefused
from smartesp.events import EventBus

from .conftest import HEADERS, PORT, TOKEN


@pytest.fixture
def streams() -> FakeSpeakerStreams:
    return FakeSpeakerStreams()


@pytest.fixture
async def api(streams: FakeSpeakerStreams) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    router = create_api(
        FakeCore(), EventBus(), TOKEN, port=PORT, files=FakeFilePlayback(), logs=LogBuffer(), streams=streams
    )
    app.include_router(router)
    add_device_streams(app, streams)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client


async def test_status_and_play(api: httpx.AsyncClient, streams: FakeSpeakerStreams) -> None:
    listed = await api.get("/api/v1/streams", headers=HEADERS)
    assert listed.status_code == 200 and listed.json()[0]["device_id"] == "d1"
    body = {"items": [{"source": "/Music/a.mp3", "title": "A"}], "start_s": 3, "volume": 0.5}
    played = await api.post("/api/v1/streams", json=body, headers=HEADERS)
    assert played.status_code == 200 and played.json()["state"] == "playing"
    assert streams.calls[-1] == ("play", (None, [StreamItem("/Music/a.mp3", "A")], 0, 3.0, 0.5))


async def test_control_and_volume(api: httpx.AsyncClient, streams: FakeSpeakerStreams) -> None:
    control = await api.post("/api/v1/streams/control", json={"action": "next"}, headers=HEADERS)
    assert control.status_code == 200 and streams.calls[-1] == ("control", (None, "next"))
    volume = await api.post(
        "/api/v1/streams/volume", json={"device_id": "d1", "delta": -0.1}, headers=HEADERS
    )
    assert volume.status_code == 200 and streams.calls[-1] == ("volume", ("d1", None, -0.1))
    bad = await api.post("/api/v1/streams/control", json={"action": "jump"}, headers=HEADERS)
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("unknown_device", 404),
        ("offline", 409),
        ("not_playing", 409),
        ("bad_source", 422),
        ("unavailable", 503),
    ],
)
async def test_refusals(
    api: httpx.AsyncClient, streams: FakeSpeakerStreams, reason: StreamRefusal, code: int
) -> None:
    streams.error = StreamRefused(reason, "Нельзя")
    response = await api.post("/api/v1/streams/control", json={"action": "pause"}, headers=HEADERS)
    assert (response.status_code, response.json()) == (code, {"detail": "Нельзя"})


async def test_needs_token(api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/v1/streams")).status_code == 401
    assert (await api.post("/api/v1/streams/control", json={"action": "stop"})).status_code == 401


async def test_device_link(api: httpx.AsyncClient, streams: FakeSpeakerStreams) -> None:
    assert (await api.get("/device/stream/abc")).status_code == 502
    streams.audio = [b"\x01\x00", b"\x02\x00"]
    response = await api.get("/device/stream/abc")
    assert response.status_code == 200 and response.content == b"\x01\x00\x02\x00"
    assert response.headers["content-type"].startswith("audio/L16")


async def test_mac_audio_inputs(api: httpx.AsyncClient, streams: FakeSpeakerStreams) -> None:
    streams.input_list = ["BlackHole 2ch"]
    response = await api.get("/api/v1/streams/inputs", headers=HEADERS)
    assert response.status_code == 200 and response.json() == ["BlackHole 2ch"]
