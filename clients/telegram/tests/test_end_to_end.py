"""Сквозной путь: апдейт Telegram → настоящий CoreClient → поддельное ядро по HTTP → ответ в чат."""

import datetime
import json

import httpx
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User

from telegram_bot.assistant import CORE_UNAUTHORIZED, Assistant
from telegram_bot.bot import build_dispatcher
from telegram_bot.core_client import CoreClient
from tests.fakes import FakeSession


def text_update(text: str) -> Update:
    message = Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=Chat(id=111, type="private"),
        from_user=User(id=111, is_bot=False, first_name="X"),
        text=text,
    )
    return Update(update_id=1, message=message)


async def run_turn(core_reply: httpx.Response, text: str) -> tuple[list[str], list[httpx.Request]]:
    seen: list[httpx.Request] = []

    async def fake_core(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return core_reply

    session = FakeSession()
    async with CoreClient("http://core", "tok", transport=httpx.MockTransport(fake_core)) as core:
        dispatcher = build_dispatcher(Assistant(core, {111: "Аня"}))
        await dispatcher.feed_update(Bot("42:TEST", session=session), text_update(text))
    return session.sent_texts(), seen


async def test_text_turn_through_http() -> None:
    sent, seen = await run_turn(httpx.Response(200, json={"answer": "Готово", "turn_id": "t"}), "включи свет")
    assert sent == ["Готово"]
    body = {"text": "включи свет", "person": "Аня", "source": "telegram", "account": "111"}
    assert json.loads(seen[0].content) == body
    assert seen[0].headers["authorization"] == "Bearer tok"


async def test_wrong_core_token() -> None:
    sent, _ = await run_turn(httpx.Response(401, json={"detail": "unauthorized"}), "привет")
    assert sent == [CORE_UNAUTHORIZED]
