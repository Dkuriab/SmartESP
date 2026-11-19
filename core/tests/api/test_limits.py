"""Тесты предела тела и ранней проверки токена: тело не читается, когда ответ уже ясен."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from fakes.fake_core import FakeCore
from smartesp.api.limits import ASK_BODY_BYTES, MAX_BODY_BYTES, VOICE_BODY_BYTES

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
