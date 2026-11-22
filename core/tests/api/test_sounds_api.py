"""API звуков: обзор, загрузка для всех и для одной колонки, встроенный, прослушивание, отказы."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from fakes.fake_sounds import FakeSoundTargets
from smartesp.api import BodyLimit, LogBuffer, create_api
from smartesp.contracts import AskUnavailable
from smartesp.events import EventBus
from smartesp.sounds import Sounds

from .conftest import HEADERS, PORT, TOKEN


async def _decode(path: Path) -> AsyncGenerator[bytes]:
    data = path.read_bytes()
    if data == b"noffmpeg":
        raise AskUnavailable("Нужен ffmpeg")
    yield data


def _beep() -> bytes:
    t = np.arange(8000) / 16000
    return np.round(0.3 * np.sin(2 * np.pi * 500 * t) * 32767).astype("<i2").tobytes()


@pytest.fixture
async def sounds_client(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, FakeSoundTargets]]:
    targets = FakeSoundTargets()
    targets.speakers = {"A": (True, {})}
    sounds = Sounds(tmp_path / "sounds", _decode, targets, targets.install)
    sounds.device_connected("A")
    app = FastAPI()
    api = create_api(
        FakeCore(), EventBus(), TOKEN, port=PORT, files=FakeFilePlayback(), logs=LogBuffer(), sounds=sounds
    )
    app.include_router(api)
    app.add_middleware(BodyLimit, token=TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client, targets
    await sounds.aclose()


def _file(data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("bell.wav", data, "audio/wav")}


A = {"device_id": "A"}


async def test_upload_overview_preview_reset_copy(
    sounds_client: tuple[httpx.AsyncClient, FakeSoundTargets],
) -> None:
    client, targets = sounds_client
    response = await client.post("/api/v1/sounds/wake", params=A, files=_file(_beep()), headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trimmed"] is False and body["sound"]["name"] == "bell.wav"
    sha = body["sound"]["sha256"]
    overview = (await client.get("/api/v1/sounds", headers=HEADERS)).json()
    device = next(d for d in overview["devices"] if d["device_id"] == "A")
    wake = next(t for t in device["tones"] if t["tone"] == "wake")
    assert wake["sound"] == body["sound"] and device["supported"] is True and "common" not in overview
    wav = await client.get(f"/api/v1/sounds/files/{sha}", headers=HEADERS)
    assert wav.status_code == 200 and wav.headers["content-type"] == "audio/wav"
    assert wav.content.startswith(b"RIFF")
    targets.speakers["B"] = (False, None)
    copied = await client.post("/api/v1/sounds/copy", params=A, headers=HEADERS)
    assert copied.status_code == 200 and copied.json() == {"devices": ["B"]}
    assert (await client.delete("/api/v1/sounds/wake", params=A, headers=HEADERS)).status_code == 204
    overview = (await client.get("/api/v1/sounds", headers=HEADERS)).json()
    sound_of = {
        d["device_id"]: next(t for t in d["tones"] if t["tone"] == "wake")["sound"]
        for d in overview["devices"]
    }
    assert sound_of["A"] is None and sound_of["B"] == body["sound"]  # копия у B своя
    assert (await client.post("/api/v1/sounds/sync", params=A, headers=HEADERS)).status_code == 202
    assert (await client.post("/api/v1/sounds/sync", headers=HEADERS)).status_code == 202


async def test_refusals(sounds_client: tuple[httpx.AsyncClient, FakeSoundTargets]) -> None:
    client, _ = sounds_client
    bad_tone = await client.post("/api/v1/sounds/bell", params=A, files=_file(_beep()), headers=HEADERS)
    assert bad_tone.status_code == 422
    no_device = await client.post("/api/v1/sounds/wake", files=_file(_beep()), headers=HEADERS)
    assert no_device.status_code == 422  # «для всех» больше нет: колонка обязательна
    unknown = await client.post(
        "/api/v1/sounds/wake", params={"device_id": "Z"}, files=_file(_beep()), headers=HEADERS
    )
    assert unknown.status_code == 404
    assert (
        await client.post("/api/v1/sounds/copy", params={"device_id": "Z"}, headers=HEADERS)
    ).status_code == 404
    empty = await client.post("/api/v1/sounds/wake", params=A, files=_file(b""), headers=HEADERS)
    assert empty.status_code == 422
    silent = await client.post("/api/v1/sounds/wake", params=A, files=_file(bytes(3200)), headers=HEADERS)
    assert silent.status_code == 422 and silent.json()["detail"] == "В файле нет звука"
    ffmpeg = await client.post("/api/v1/sounds/wake", params=A, files=_file(b"noffmpeg"), headers=HEADERS)
    assert ffmpeg.status_code == 503
    assert (await client.get("/api/v1/sounds/files/" + "0" * 64, headers=HEADERS)).status_code == 404
    assert (await client.get("/api/v1/sounds")).status_code == 401


async def test_without_sounds_is_409(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/sounds", headers=HEADERS)).status_code == 409
