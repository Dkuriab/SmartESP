"""Обработчики aiogram целиком: апдейт → диспетчер → поддельные ядро и Bot API."""

import datetime
import logging
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, PhotoSize, Update, User, Voice

from telegram_bot.assistant import CORE_UNAVAILABLE, NO_BARCODE, Assistant
from telegram_bot.bot import DOWNLOAD_FAILED, GREETING, MAX_MESSAGE, UNSUPPORTED, build_dispatcher
from telegram_bot.core_client import CoreUnavailableError
from tests.fakes import FakeCore, FakeSession

ALLOWED = 111
STRANGER = 999


class Harness:
    """Бот с поддельной сессией и поддельным ядром; `send` — прогнать сообщение."""

    def __init__(self, core: FakeCore, barcode: str | None = None) -> None:
        self.core = core
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        assistant = Assistant(core, {ALLOWED: "Аня"}, barcode_reader=lambda photo: barcode)
        self.dispatcher = build_dispatcher(assistant)

    async def send(self, user_id: int = ALLOWED, chat_type: str = "private", **fields: Any) -> None:
        message = Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=user_id, type=chat_type),
            from_user=User(id=user_id, is_bot=False, first_name="X"),
            **fields,
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=1, message=message))


async def test_text_is_answered_while_typing() -> None:
    harness = Harness(FakeCore("Привет, Аня!", delay=0.05))
    await harness.send(text="привет")
    assert harness.core.calls == [("text", "привет", "Аня", "111")]
    assert harness.session.sent_texts() == ["Привет, Аня!"]
    assert "typing" in harness.session.actions()


async def test_stranger_gets_silence_and_text_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    harness = Harness(FakeCore())
    with caplog.at_level(logging.INFO):
        await harness.send(user_id=STRANGER, text="секретный текст")
    assert harness.core.calls == []
    assert harness.session.requests == []
    assert str(STRANGER) in caplog.text
    assert "секретный текст" not in caplog.text


async def test_group_chats_are_ignored() -> None:
    harness = Harness(FakeCore())
    await harness.send(chat_type="group", text="привет")
    assert harness.core.calls == []
    assert harness.session.requests == []


async def test_voice_is_downloaded_and_sent_to_core() -> None:
    harness = Harness(FakeCore("Слышу"))
    harness.session.files["voice-1"] = b"OggS-audio"
    await harness.send(voice=Voice(file_id="voice-1", file_unique_id="v", duration=2))
    assert harness.core.calls == [("voice", b"OggS-audio", "Аня", "111")]
    assert harness.session.sent_texts() == ["Слышу"]


async def test_failed_download_is_reported() -> None:
    harness = Harness(FakeCore())
    await harness.send(voice=Voice(file_id="missing", file_unique_id="v", duration=2))
    assert harness.core.calls == []
    assert harness.session.sent_texts() == [DOWNLOAD_FAILED]


async def test_photo_uses_largest_size_and_caption() -> None:
    harness = Harness(FakeCore("Записано"), barcode="4601234567893")
    harness.session.files["big"] = b"jpeg"
    sizes = [
        PhotoSize(file_id="small", file_unique_id="s", width=90, height=60),
        PhotoSize(file_id="big", file_unique_id="b", width=1280, height=960),
    ]
    await harness.send(photo=sizes, caption="200 г")
    assert harness.core.calls == [("text", "штрихкод 4601234567893, 200 г", "Аня", "111")]
    assert harness.session.sent_texts() == ["Записано"]


async def test_photo_without_barcode() -> None:
    harness = Harness(FakeCore(), barcode=None)
    harness.session.files["big"] = b"jpeg"
    await harness.send(photo=[PhotoSize(file_id="big", file_unique_id="b", width=10, height=10)])
    assert harness.session.sent_texts() == [NO_BARCODE]


async def test_core_down_reply() -> None:
    harness = Harness(FakeCore(error=CoreUnavailableError("down")))
    await harness.send(text="привет")
    assert harness.session.sent_texts() == [CORE_UNAVAILABLE]


async def test_long_answer_is_split() -> None:
    harness = Harness(FakeCore("а" * (MAX_MESSAGE + 10)))
    await harness.send(text="расскажи")
    assert [len(t) for t in harness.session.sent_texts()] == [MAX_MESSAGE, 10]


async def test_start_greets_without_core() -> None:
    harness = Harness(FakeCore())
    await harness.send(text="/start")
    assert harness.core.calls == []
    assert harness.session.sent_texts() == [GREETING]


async def test_other_content_gets_a_hint() -> None:
    harness = Harness(FakeCore())
    await harness.send(location={"latitude": 55.0, "longitude": 37.0})
    assert harness.core.calls == []
    assert harness.session.sent_texts() == [UNSUPPORTED]
