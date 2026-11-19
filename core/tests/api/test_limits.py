"""Тесты предела тела и ранней проверки токена: тело не читается, когда ответ уже ясен."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from smartesp.api.limits import (
    ASK_BODY_BYTES,
    MAX_BODY_BYTES,
    PLAY_BODY_BYTES,
    VOICE_BODY_BYTES,
    guarded_limit,
)
from smartesp.api.play import MAX_FILE_BYTES

from .conftest import HEADERS

MB = 1024 * 1024


class Body:
    """Тело кусками по 1 МБ (chunked, без Content-Length); считает, сколько кусков прочитали."""

    def __init__(self, chunks: int, size: int = MB) -> None:
        self.chunks = chunks
        self.size = size
        self.read = 0

    async def stream(self) -> AsyncIterator[bytes]:
        for _ in range(self.chunks):
            self.read += 1
            yield b"\x00" * self.size


VOICE_HEAD = (
    b'--b\r\nContent-Disposition: form-data; name="audio"; filename="voice.ogg"\r\n'
    b"Content-Type: audio/ogg\r\n\r\n"
)
PLAY_HEAD = (
    b'--b\r\nContent-Disposition: form-data; name="audio"; filename="song.mp3"\r\n'
    b"Content-Type: audio/mpeg\r\n\r\n"
)
MULTIPART = {"Content-Type": "multipart/form-data; boundary=b"}


@pytest.mark.parametrize(
    ("path", "limit"), [("/api/v1/ask", ASK_BODY_BYTES), ("/api/v1/ask/voice", VOICE_BODY_BYTES)]
)
async def test_declared_length_over_limit_is_413_unread(
    client: httpx.AsyncClient, core: FakeCore, path: str, limit: int
) -> None:
    body = Body(100)
    headers = {**HEADERS, "Content-Length": str(limit + 1)}
    response = await client.post(path, content=body.stream(), headers=headers)
    assert response.status_code == 413
    assert response.json() == {"detail": "Тело запроса слишком большое"}
    assert body.read == 0
    assert (core.questions, core.voices_asked) == ([], [])


async def test_chunked_voice_over_limit_is_413_without_reading_all(
    client: httpx.AsyncClient, core: FakeCore
) -> None:
    body = Body(50)

    async def stream() -> AsyncIterator[bytes]:
        yield VOICE_HEAD
        async for chunk in body.stream():
            yield chunk

    response = await client.post("/api/v1/ask/voice", content=stream(), headers={**HEADERS, **MULTIPART})
    assert response.status_code == 413
    assert body.read <= VOICE_BODY_BYTES // MB + 2  # чтение оборвано сразу за пределом
    assert core.voices_asked == []


async def test_chunked_text_over_limit_is_413(client: httpx.AsyncClient, core: FakeCore) -> None:
    body = Body(20, size=ASK_BODY_BYTES // 2)
    headers = {**HEADERS, "Content-Type": "application/json"}
    response = await client.post("/api/v1/ask", content=body.stream(), headers=headers)
    assert response.status_code == 413
    assert body.read <= 3
    assert core.questions == []


@pytest.mark.parametrize("path", ["/api/v1/ask", "/api/v1/ask/voice"])
async def test_no_token_big_body_is_401_unread(client: httpx.AsyncClient, path: str) -> None:
    body = Body(100)
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = await client.post(path, content=body.stream(), headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}
    assert body.read == 0


async def test_global_cap_for_other_routes(client: httpx.AsyncClient, core: FakeCore) -> None:
    body = Body(MAX_BODY_BYTES // MB + 10)
    headers = {**HEADERS, "Content-Type": "application/json"}
    response = await client.patch("/api/v1/config", content=body.stream(), headers=headers)
    assert response.status_code == 413
    assert body.read <= MAX_BODY_BYTES // MB + 2
    assert core.patches == []


async def test_normal_requests_pass(client: httpx.AsyncClient, core: FakeCore) -> None:
    assert (await client.post("/api/v1/ask", json={"text": "Привет"}, headers=HEADERS)).status_code == 200
    files = {"audio": ("voice.ogg", b"\x00" * (10 * MB), "audio/ogg")}  # ровно 10 МБ звука проходит
    assert (await client.post("/api/v1/ask/voice", files=files, headers=HEADERS)).status_code == 200
    assert (await client.patch("/api/v1/config", json={"tts": {}}, headers=HEADERS)).status_code == 200
    assert (await client.get("/api/v1/status", headers=HEADERS)).status_code == 200


PLAY = "/api/v1/devices/aa:bb:cc:dd:ee:ff/play"


async def test_play_declared_over_limit_is_413_unread(
    client: httpx.AsyncClient, files: FakeFilePlayback
) -> None:
    body = Body(100)
    headers = {**HEADERS, **MULTIPART, "Content-Length": str(PLAY_BODY_BYTES + 1)}
    response = await client.post(PLAY, content=body.stream(), headers=headers)
    assert response.status_code == 413
    assert body.read == 0
    assert files.plays == []


async def test_play_chunked_over_limit_is_413(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    body = Body(80)

    async def stream() -> AsyncIterator[bytes]:
        yield PLAY_HEAD
        async for chunk in body.stream():
            yield chunk

    response = await client.post(PLAY, content=stream(), headers={**HEADERS, **MULTIPART})
    assert response.status_code == 413
    assert body.read <= PLAY_BODY_BYTES // MB + 2
    assert files.plays == []


async def test_play_no_token_is_401_unread(client: httpx.AsyncClient) -> None:
    body = Body(100)
    response = await client.post(PLAY, content=body.stream(), headers=MULTIPART)
    assert response.status_code == 401
    assert body.read == 0


async def test_play_allows_more_than_global_cap(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    upload = {"audio": ("song.mp3", b"\x00" * (MAX_FILE_BYTES), "audio/mpeg")}  # ровно 50 МБ проходит
    response = await client.post(PLAY, files=upload, headers=HEADERS)
    assert response.status_code == 202
    assert len(files.plays[0][1]) == MAX_FILE_BYTES


@pytest.mark.parametrize(
    "path", ["/api/v1/devices/a/b/play", "/api/v1/devices/a/play/x", "/api/v1/devices//play"]
)
def test_play_pattern_is_exact(path: str) -> None:
    assert guarded_limit("POST", path) is None


def test_play_pattern_only_for_post() -> None:
    assert guarded_limit("POST", PLAY) == PLAY_BODY_BYTES
    assert guarded_limit("DELETE", PLAY) is None
    assert guarded_limit("POST", "/api/v1/ask") == ASK_BODY_BYTES
