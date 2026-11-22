"""Тонкая прослойка aiogram: достаёт из сообщений текст, голос и фото и зовёт `Assistant`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import Message, TelegramObject
from aiogram.utils.chat_action import ChatActionSender
from aiohttp import ClientError

from .assistant import Assistant

log = logging.getLogger(__name__)

MAX_MESSAGE = 4096  # предел длины сообщения в Telegram
GREETING = "Привет! Пиши, присылай голосовые или фото штрихкода — передам Кузе."
UNSUPPORTED = "Понимаю текст, голосовые и фото штрихкода."
DOWNLOAD_FAILED = "Не получилось скачать файл из Telegram — попробуй ещё раз."


class AccessMiddleware(BaseMiddleware):
    """Пропускает только допущенных людей и кладёт имя человека в `person`.

    Чужим — молчание; в журнал — только `user_id`, без текста сообщения.
    """

    def __init__(self, assistant: Assistant, on_stranger: Callable[[int, str], None] | None = None) -> None:
        """on_stranger(user_id, имя) — незнакомый написал (бот от ядра: предложить «Добавить»)."""
        self._assistant = assistant
        self._on_stranger = on_stranger

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user if isinstance(event, Message) else None
        user_id = user.id if user is not None else None
        person = self._assistant.person(user_id)
        if person is None:
            log.info("Сообщение от недопущенного user_id=%s пропущено", user_id)
            if user is not None and self._on_stranger is not None:
                self._on_stranger(user.id, user.full_name or user.username or "")
            return None
        data["person"] = person
        return await handler(event, data)


def build_dispatcher(
    assistant: Assistant, on_stranger: Callable[[int, str], None] | None = None
) -> Dispatcher:
    """Собирает диспетчер: личные чаты, доступ по списку, обработчики сообщений."""
    router = Router(name="smartesp")
    router.message.outer_middleware(AccessMiddleware(assistant, on_stranger))
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.message.register(_on_start, CommandStart())
    router.message.register(_on_text, F.text)
    router.message.register(_on_voice, F.voice)
    router.message.register(_on_photo, F.photo)
    router.message.register(_on_other)
    dispatcher = Dispatcher(assistant=assistant)
    dispatcher.include_router(router)
    return dispatcher


async def _on_start(message: Message) -> None:
    await message.answer(GREETING)


async def _on_text(message: Message, bot: Bot, assistant: Assistant, person: str) -> None:
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        reply = await assistant.text(person, message.text or "")
    await _reply(message, reply)


async def _on_voice(message: Message, bot: Bot, assistant: Assistant, person: str) -> None:
    assert message.voice is not None  # гарантирует фильтр F.voice
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        audio = await _download(bot, message.voice.file_id)
        reply = DOWNLOAD_FAILED if audio is None else await assistant.voice(person, audio)
    await _reply(message, reply)


async def _on_photo(message: Message, bot: Bot, assistant: Assistant, person: str) -> None:
    assert message.photo  # гарантирует фильтр F.photo
    largest = max(message.photo, key=lambda size: size.width * size.height)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        photo = await _download(bot, largest.file_id)
        reply = DOWNLOAD_FAILED if photo is None else await assistant.photo(person, photo, message.caption)
    await _reply(message, reply)


async def _on_other(message: Message) -> None:
    await message.answer(UNSUPPORTED)


async def _download(bot: Bot, file_id: str) -> bytes | None:
    """Скачивает файл сообщения в память; не вышло — None (причина — в журнал)."""
    try:
        buffer = await bot.download(file_id)
    except (TelegramAPIError, ClientError, TimeoutError) as error:
        log.warning("Не скачался файл из Telegram: %s", type(error).__name__)
        return None
    return buffer.read() if buffer is not None else None


async def _reply(message: Message, text: str) -> None:
    """Отправляет ответ, деля длинный текст на сообщения по `MAX_MESSAGE` символов."""
    for start in range(0, len(text), MAX_MESSAGE):
        await message.answer(text[start : start + MAX_MESSAGE])
