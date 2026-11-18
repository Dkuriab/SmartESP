"""Адаптер Starlette WebSocket → DeviceConnection: любой обрыв связи — ConnectionError."""

from __future__ import annotations

import asyncio
import logging

from starlette.websockets import WebSocket, WebSocketDisconnect

CLOSE_TIMEOUT_S = 1.0  # дольше ждать закрытия зависшей колонки нет смысла

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """Соединение колонки поверх Starlette WebSocket (реализует DeviceConnection).

    Хаб различает только «кадр пришёл/ушёл» и ConnectionError, поэтому все виды
    обрыва (disconnect, отправка после закрытия, ошибки uvicorn/websockets)
    переводятся в ConnectionError. Отмену задачи (CancelledError) не трогаем.
    """

    def __init__(self, ws: WebSocket) -> None:
        """ws — уже принятый (accept) WebSocket."""
        self._ws = ws
        self._closed = False
        client = ws.client
        self._remote = f"{client.host}:{client.port}" if client is not None else "unknown"

    @property
    def remote(self) -> str:
        """Адрес колонки «host:port» ("unknown", если сервер его не знает)."""
        return self._remote

    async def receive(self) -> str | bytes:
        """Ждёт следующий кадр: текст или звук. ConnectionError — соединение закрыто."""
        if self._closed:
            raise ConnectionError("соединение закрыто")
        try:
            message = await self._ws.receive()
        except (WebSocketDisconnect, RuntimeError, OSError) as error:
            raise ConnectionError(f"обрыв связи с {self._remote}") from error
        if message["type"] == "websocket.disconnect":
            raise ConnectionError(f"колонка {self._remote} отключилась")
        text = message.get("text")
        if text is not None:
            return text
        data = message.get("bytes")
        return data if data is not None else b""

    async def send_text(self, text: str) -> None:
        """Шлёт текстовый кадр. ConnectionError — соединение закрыто."""
        self._check_open()
        try:
            await self._ws.send_text(text)
        except Exception as error:  # любой сбой отправки — обрыв связи
            logger.debug("send_text to %s failed: %r", self._remote, error)
            raise ConnectionError(f"не удалось отправить на {self._remote}") from error

    async def send_bytes(self, data: bytes) -> None:
        """Шлёт звуковой кадр. ConnectionError — соединение закрыто."""
        self._check_open()
        try:
            await self._ws.send_bytes(data)
        except Exception as error:  # любой сбой отправки — обрыв связи
            logger.debug("send_bytes to %s failed: %r", self._remote, error)
            raise ConnectionError(f"не удалось отправить на {self._remote}") from error

    async def close(self) -> None:
        """Закрывает соединение. Не кидает исключений и ждёт не дольше CLOSE_TIMEOUT_S."""
        if self._closed:
            return
        self._closed = True
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT_S):
                await self._ws.close()
        except Exception as error:  # уже закрыто, оборвано или зависло — всё равно закрыто
            logger.debug("close of %s: %r", self._remote, error)

    def _check_open(self) -> None:
        if self._closed:
            raise ConnectionError("соединение закрыто")
