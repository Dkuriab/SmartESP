"""Адаптер Starlette WebSocket → DeviceConnection: кадры и перевод обрывов в ConnectionError."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketDisconnected

from smartesp.devices import WebSocketConnection
from smartesp.devices import websocket_connection as module


class FakeClient:
    host = "10.0.0.7"
    port = 5000


class FakeStarletteSocket:
    """Похож на starlette.websockets.WebSocket: receive/send_text/send_bytes/close."""

    def __init__(self) -> None:
        self.client: FakeClient | None = FakeClient()
        self.incoming: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        self.sent: list[str | bytes] = []
        self.send_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.close_hangs = False
        self.close_calls = 0

    async def receive(self) -> dict[str, Any]:
        item = await self.incoming.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_text(self, data: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    async def send_bytes(self, data: bytes) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_calls += 1
        if self.close_hangs:
            await asyncio.Event().wait()
        if self.close_error is not None:
            raise self.close_error


def adapt(ws: FakeStarletteSocket) -> WebSocketConnection:
    return WebSocketConnection(cast(WebSocket, ws))


def test_remote_is_host_and_port() -> None:
    ws = FakeStarletteSocket()
    assert adapt(ws).remote == "10.0.0.7:5000"
    ws.client = None
    assert adapt(ws).remote == "unknown"


async def test_receive_returns_text_and_bytes() -> None:
    ws = FakeStarletteSocket()
    conn = adapt(ws)
    ws.incoming.put_nowait({"type": "websocket.receive", "text": '{"type":"hello"}'})
    ws.incoming.put_nowait({"type": "websocket.receive", "bytes": b"\x01\x02"})
    assert await conn.receive() == '{"type":"hello"}'
    assert await conn.receive() == b"\x01\x02"


async def test_receive_disconnect_message_raises_connection_error() -> None:
    ws = FakeStarletteSocket()
    ws.incoming.put_nowait({"type": "websocket.disconnect", "code": 1006})
    with pytest.raises(ConnectionError):
        await adapt(ws).receive()


@pytest.mark.parametrize(
    "error",
    [WebSocketDisconnect(1006), WebSocketDisconnected("closed"), RuntimeError("after close")],
)
async def test_receive_errors_become_connection_error(error: Exception) -> None:
    ws = FakeStarletteSocket()
    ws.incoming.put_nowait(error)
    with pytest.raises(ConnectionError):
        await adapt(ws).receive()


@pytest.mark.parametrize(
    "error",
    [WebSocketDisconnect(1006), RuntimeError("send after close"), OSError("reset"), Exception("closed")],
)
async def test_send_errors_become_connection_error(error: Exception) -> None:
    ws = FakeStarletteSocket()
    ws.send_error = error
    conn = adapt(ws)
    with pytest.raises(ConnectionError):
        await conn.send_text("{}")
    with pytest.raises(ConnectionError):
        await conn.send_bytes(b"\x00")


async def test_send_passes_frames_through() -> None:
    ws = FakeStarletteSocket()
    conn = adapt(ws)
    await conn.send_text("{}")
    await conn.send_bytes(b"\x00\x01")
    assert ws.sent == ["{}", b"\x00\x01"]


async def test_send_does_not_swallow_cancellation() -> None:
    ws = FakeStarletteSocket()
    ws.send_error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await adapt(ws).send_text("{}")


async def test_close_never_raises_and_later_calls_fail() -> None:
    ws = FakeStarletteSocket()
    ws.close_error = RuntimeError("already closed")
    conn = adapt(ws)
    await conn.close()
    await conn.close()  # повторно — тоже без ошибок
    assert ws.close_calls == 1
    with pytest.raises(ConnectionError):
        await conn.receive()
    with pytest.raises(ConnectionError):
        await conn.send_text("{}")


async def test_close_does_not_block_on_hung_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "CLOSE_TIMEOUT_S", 0.05)
    ws = FakeStarletteSocket()
    ws.close_hangs = True
    async with asyncio.timeout(1.0):
        await adapt(ws).close()
