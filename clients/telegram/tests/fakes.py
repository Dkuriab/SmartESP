"""Подделки для тестов: ядро и сессия Telegram Bot API (без сети)."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncGenerator
from typing import Any, cast

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, SendChatAction, SendMessage, TelegramMethod
from aiogram.types import Chat, File, Message

from telegram_bot.core_client import CoreError


class FakeCore:
    """Поддельное ядро: запоминает ходы, отвечает заданным текстом или ошибкой."""

    def __init__(self, answer: str = "Ответ Кузи", error: CoreError | None = None, delay: float = 0) -> None:
        self.answer = answer
        self.error = error
        self.delay = delay
        self.calls: list[tuple[str, object, str, str]] = []  # (вид, содержимое, имя, аккаунт)

    async def ask(self, text: str, *, person: str, account: str = "") -> str:
        self.calls.append(("text", text, person, account))
        return await self._reply()

    async def ask_voice(self, audio: bytes, *, person: str, account: str = "") -> str:
        self.calls.append(("voice", audio, person, account))
        return await self._reply()

    async def _reply(self) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.answer


class FakeSession(BaseSession):
    """Сессия Bot API в памяти: запоминает вызовы, отдаёт файлы из `files` (file_id → байты)."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.files: dict[str, bytes] = {}

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            chat = Chat(id=cast(int, method.chat_id), type="private")
            return Message(message_id=len(self.requests), date=datetime.datetime.now(), chat=chat)
        if isinstance(method, SendChatAction):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path=f"files/{method.file_id}")
        raise AssertionError(f"неожиданный вызов Bot API: {type(method).__name__}")

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        file_id = url.rsplit("/", 1)[-1]
        if file_id not in self.files:
            raise TimeoutError("файл не скачался")
        yield self.files[file_id]

    def sent_texts(self) -> list[str]:
        """Тексты отправленных в чат сообщений."""
        return [m.text for m in self.requests if isinstance(m, SendMessage)]

    def actions(self) -> list[str]:
        """Отправленные действия чата («печатает…»)."""
        return [m.action for m in self.requests if isinstance(m, SendChatAction)]
