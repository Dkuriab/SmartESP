"""Клиент ядра против поддельного ядра (httpx.MockTransport)."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from telegram_bot.core_client import (
    CoreClient,
    CoreRejectedError,
    CoreUnauthorizedError,
    CoreUnavailableError,
)

Handler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]


def client(handler: Handler, *, timeout: float = 60.0) -> CoreClient:
    return CoreClient("http://core:8765", "tok", timeout=timeout, transport=httpx.MockTransport(handler))


async def test_ask_sends_text_person_and_source() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"answer": "Привет!", "turn_id": "t1"})

    async with client(handler) as core:
        assert await core.ask("привет", person="Аня") == "Привет!"
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://core:8765/api/v1/ask"
    assert request.headers["authorization"] == "Bearer tok"
    assert json.loads(request.content) == {"text": "привет", "person": "Аня", "source": "telegram"}


async def test_ask_voice_sends_multipart_audio() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"answer": "Слышу", "turn_id": "t2"})

    async with client(handler) as core:
        assert await core.ask_voice(b"OggS-audio", person="Аня") == "Слышу"
    request = seen[0]
    assert str(request.url) == "http://core:8765/api/v1/ask/voice"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.read()
    assert b'name="audio"; filename="voice.ogg"' in body
    assert b"Content-Type: audio/ogg" in body
    assert b"OggS-audio" in body
    assert b'name="person"' in body and "Аня".encode() in body
    assert b'name="source"' in body and b"telegram" in body


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, CoreUnauthorizedError),
        (403, CoreUnauthorizedError),
        (400, CoreRejectedError),
        (413, CoreRejectedError),
        (422, CoreRejectedError),
        (500, CoreUnavailableError),
        (503, CoreUnavailableError),
        (404, CoreUnavailableError),
    ],
)
async def test_error_statuses(status: int, error: type[Exception]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "nope"})

    async with client(handler) as core:
        with pytest.raises(error):
            await core.ask("x", person="Аня")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"turn_id": "t"}),
        httpx.Response(200, json={"answer": 5}),
        httpx.Response(200, json=["answer"]),
    ],
)
async def test_malformed_answer_is_unavailable(response: httpx.Response) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    async with client(handler) as core:
        with pytest.raises(CoreUnavailableError):
            await core.ask("x", person="Аня")


async def test_connection_error_is_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with client(handler) as core:
        with pytest.raises(CoreUnavailableError):
            await core.ask_voice(b"x", person="Аня")


async def test_slow_core_hits_overall_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"answer": "поздно", "turn_id": "t"})

    async with client(handler, timeout=0.05) as core:
        with pytest.raises(CoreUnavailableError):
            await core.ask("x", person="Аня")


def test_trailing_slash_in_base_url() -> None:
    core = CoreClient("http://core:8765/", "tok")
    assert core.base_url == "http://core:8765"
