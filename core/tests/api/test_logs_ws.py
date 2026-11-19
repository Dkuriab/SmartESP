"""Тесты журнала: буфер строк и WebSocket /api/v1/logs."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from smartesp.api import LogBuffer

from .conftest import TOKEN


def emit(buffer: LogBuffer, message: str, level: int = logging.INFO, *args: object) -> None:
    buffer.handle(logging.LogRecord("smartesp", level, __file__, 1, message, args or None, None))


def test_buffer_keeps_last_lines_and_hides_token() -> None:
    buffer = LogBuffer(recent=3)
    for i in range(5):
        emit(buffer, "строка %d", logging.INFO, i)
    emit(buffer, "GET /?token=%s", logging.WARNING, "секрет")

    async def check() -> None:
        recent, subscription = buffer.subscribe()
        await subscription.aclose()
        assert [line.level for line in recent] == ["INFO", "INFO", "WARNING"]
        assert recent[0].text.endswith("smartesp: строка 3")
        assert "секрет" not in recent[-1].text and "token=***" in recent[-1].text

    asyncio.run(check())


def test_buffer_rejects_bad_sizes() -> None:
    with pytest.raises(ValueError):
        LogBuffer(recent=0)
    with pytest.raises(ValueError):
        LogBuffer(queue_size=0)


async def test_slow_subscriber_loses_oldest_lines_only() -> None:
    buffer = LogBuffer(recent=2, queue_size=3)
    _, subscription = buffer.subscribe()
    for i in range(10):
        emit(buffer, f"новая {i}")
    await asyncio.sleep(0)  # строки кладутся через call_soon_threadsafe
    got = [(await subscription.get()).text.rsplit(" ", 1)[-1] for _ in range(3)]
    assert got == ["7", "8", "9"]
    assert subscription.dropped == 7
    await subscription.aclose()
    await subscription.aclose()  # повторно — можно
    assert buffer.subscriber_count == 0


async def test_line_from_other_thread_reaches_subscriber() -> None:
    buffer = LogBuffer()
    _, subscription = buffer.subscribe()
    thread = threading.Thread(target=emit, args=(buffer, "из потока"))
    thread.start()
    thread.join()
    line = await asyncio.wait_for(subscription.get(), 2)
    assert line.text.endswith("из потока")
    await subscription.aclose()


@pytest.mark.parametrize("query", ["", "?token=wrong", "?token="])
def test_logs_ws_bad_token_closes_4401(app: FastAPI, logs: LogBuffer, query: str) -> None:
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect(f"/api/v1/logs{query}") as ws:
            ws.receive_text()
    assert info.value.code == 4401
    assert logs.subscriber_count == 0


def _wait(condition: object, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(condition) and condition():
            return True
        time.sleep(0.02)
    return False


def test_logs_ws_sends_recent_then_live_and_unsubscribes(app: FastAPI, logs: LogBuffer) -> None:
    emit(logs, "раньше")
    emit(logs, "сбой", logging.ERROR)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/logs?token={TOKEN}") as ws:
            first, second = ws.receive_json(), ws.receive_json()
            assert set(first) == {"at", "level", "text"}
            assert (first["level"], second["level"]) == ("INFO", "ERROR")
            assert first["text"].endswith("раньше") and isinstance(first["at"], float)
            assert _wait(lambda: logs.subscriber_count == 1)
            emit(logs, "потом token=abc")
            live = ws.receive_json()
            assert live["text"].endswith("потом token=***")
        assert _wait(lambda: logs.subscriber_count == 0)
