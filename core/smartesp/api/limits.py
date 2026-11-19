"""Предел размера тела запроса и ранняя проверка токена — до чтения тела (чистый ASGI).

FastAPI читает тело (multipart — в файл на диске без предела) раньше зависимостей с
токеном. Поэтому для ходов через API токен проверяется здесь, по заголовкам, а размер —
по Content-Length сразу и по счёту байтов для тела без длины (chunked): перебор — 413,
дальше тело не читается. Остальным запросам — общий предел MAX_BODY_BYTES.
"""

from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import bearer_token, token_matches

MAX_BODY_BYTES = 12 * 1024 * 1024  # общий предел тела любого запроса
ASK_BODY_BYTES = 64 * 1024  # POST /ask: JSON с текстом
VOICE_BODY_BYTES = 10 * 1024 * 1024 + 64 * 1024  # POST /ask/voice: 10 МБ звука и обвязка multipart
GUARDED = {"/api/v1/ask": ASK_BODY_BYTES, "/api/v1/ask/voice": VOICE_BODY_BYTES}  # токен — до тела
TOO_LARGE = "Тело запроса слишком большое"


class _TooLarge(HTTPException):
    """Тело перевалило за предел посреди чтения: FastAPI отдаст его как 413."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=TOO_LARGE)


class BodyLimit:
    """ASGI-прослойка: предел тела для всех запросов, для ходов через API — и токен до тела."""

    def __init__(self, app: ASGIApp, token: str, max_body: int = MAX_BODY_BYTES) -> None:
        """app — приложение; token — токен API; max_body — общий предел тела в байтах."""
        self._app = app
        self._token = token
        self._max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Пропускает запрос дальше или сразу отвечает 401/413, не читая тело."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        limit = self._max_body
        if scope["method"] == "POST" and scope["path"] in GUARDED:
            if not token_matches(bearer_token(headers.get("authorization")), self._token):
                await _reply(send, 401, "unauthorized")
                return
            limit = GUARDED[scope["path"]]
        if _declared(headers) > limit:
            await _reply(send, 413, TOO_LARGE)
            return
        await self._limited(scope, receive, send, limit)

    async def _limited(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        """Запрос с подсчётом байтов тела; перебор до начала ответа — 413."""
        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if started:
                raise
            await _reply(send, 413, TOO_LARGE)


def _declared(headers: dict[str, str]) -> int:
    """Длина тела из Content-Length; нет или неверная — 0 (тогда считаем байты по ходу)."""
    try:
        return max(0, int(headers.get("content-length", "0")))
    except ValueError:
        return 0


async def _reply(send: Send, status: int, detail: str) -> None:
    """Короткий ответ JSON {"detail"} с закрытием соединения: остаток тела не читаем."""
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"connection", b"close"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
