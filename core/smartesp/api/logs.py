"""WebSocket журнала `/api/v1/logs`: последние строки, затем новые; токен — в `?token=`."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket

from .auth import token_matches
from .log_buffer import LogBuffer, LogLine, LogSubscription

WS_UNAUTHORIZED = 4401


def add_logs_route(router: APIRouter, logs: LogBuffer, token: str) -> None:
    """Подключает `/logs`: каждое сообщение — JSON {at, level, text} одной строки журнала."""

    @router.websocket("/logs")
    async def stream_logs(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        # Сначала accept: так клиент получает код закрытия 4401, а не голый HTTP 403.
        await websocket.accept()
        if not token_matches(websocket.query_params.get("token"), token):
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        recent, subscription = logs.subscribe()
        sender = asyncio.create_task(_send_lines(websocket, recent, subscription))
        receiver = asyncio.create_task(_wait_disconnect(websocket))
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            logs.unsubscribe(subscription)  # до первого await: сама задача может быть уже отменена
            for task in (sender, receiver):
                task.cancel()
            await asyncio.wait({sender, receiver})


def _payload(line: LogLine) -> str:
    return json.dumps({"at": line.at, "level": line.level, "text": line.text}, ensure_ascii=False)


async def _send_lines(websocket: WebSocket, recent: list[LogLine], subscription: LogSubscription) -> None:
    """Шлёт сначала последние строки, затем новые по мере появления."""
    for line in recent:
        await websocket.send_text(_payload(line))
    while True:
        await websocket.send_text(_payload(await subscription.get()))


async def _wait_disconnect(websocket: WebSocket) -> None:
    """Читает сокет, пока клиент не отключится (иначе обрыв не заметить)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
