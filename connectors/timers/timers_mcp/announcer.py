"""Объявления ядру: MCP-уведомление журнала, в том числе вне вызова инструмента.

Сессию последнего подключения запоминает прослойка сервера (`ServerMiddleware`):
она видит каждое входящее сообщение, включая `notifications/initialized`.
Уведомление без `related_request_id` идёт по постоянному каналу соединения
(stdio-труба), поэтому его можно слать из фоновой задачи. Пока сессии нет
(коннектор только запустился), объявления копятся и уходят при подключении.
"""

import logging
from typing import Any

import anyio
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.session import ServerSession
from mcp_types import LoggingMessageNotification, LoggingMessageNotificationParams

LOGGER_NAME = "smartesp"

logger = logging.getLogger(__name__)


class Announcer:
    """Шлёт ядру `{"type": "announce", "text", "person"}` и задачи «В работе»
    `{"type": "task", "id", "title", "status", "eta", "person"}` в сессию последнего подключения."""

    def __init__(self) -> None:
        self._session: ServerSession | None = None
        self._pending: list[dict[str, Any]] = []
        self._sending = anyio.Lock()

    async def announce(self, text: str, person: str | None) -> None:
        """Объявляет текст для человека (None — для дома); без подключения — откладывает."""
        self._pending.append({"type": "announce", "text": text, "person": person})
        await self._flush()

    async def task(self, task_id: str, title: str, status: str, eta: str | None, person: str | None) -> None:
        """Сообщает ядру о задаче «В работе» (status: running, done, cancelled; eta — ISO 8601)."""
        data = {"type": "task", "id": task_id, "title": title, "status": status, "eta": eta, "person": person}
        self._pending.append(data)
        await self._flush()

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        """Прослойка сервера: запоминает сессию каждого сообщения, кроме `initialize`."""
        result = await call_next(ctx)
        if ctx.method != "initialize":
            self._session = ctx.session
            await self._flush()
        return result

    async def _flush(self) -> None:
        async with self._sending:
            await self._send_pending()

    async def _send_pending(self) -> None:
        while self._session is not None and self._pending:
            data = self._pending[0]
            note = LoggingMessageNotification(
                params=LoggingMessageNotificationParams(level="info", logger=LOGGER_NAME, data=data)
            )
            try:
                await self._session.send_notification(note)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                logger.warning("соединение закрыто, объявление подождёт нового подключения")
                self._session = None
                return
            self._pending.pop(0)
