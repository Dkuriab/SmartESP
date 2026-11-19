"""Логика бота без Telegram: кто допущен, что уходит ядру, какие ответы на ошибки."""

import logging

import pytest

from telegram_bot.assistant import (
    CORE_EMPTY,
    CORE_REJECTED,
    CORE_UNAUTHORIZED,
    CORE_UNAVAILABLE,
    NO_BARCODE,
    Assistant,
)
from telegram_bot.core_client import (
    CoreError,
    CoreRejectedError,
    CoreUnauthorizedError,
    CoreUnavailableError,
)


class FakeCore:
    """Поддельное ядро: запоминает ходы, отвечает заданным текстом или ошибкой."""

    def __init__(self, answer: str = "Ответ Кузи", error: CoreError | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[str, object, str]] = []

    async def ask(self, text: str, *, person: str) -> str:
        self.calls.append(("text", text, person))
        return self._reply()

    async def ask_voice(self, audio: bytes, *, person: str) -> str:
        self.calls.append(("voice", audio, person))
        return self._reply()

    def _reply(self) -> str:
        if self.error is not None:
            raise self.error
        return self.answer


def assistant(core: FakeCore, barcode: str | None = None) -> Assistant:
    return Assistant(core, {111: "Аня"}, barcode_reader=lambda photo: barcode)


def test_person_only_for_allowed_users() -> None:
    bot = assistant(FakeCore())
    assert bot.person(111) == "Аня"
    assert bot.person(222) is None
    assert bot.person(None) is None


async def test_text_goes_to_core_with_person() -> None:
    core = FakeCore("Привет, Аня!")
    assert await assistant(core).text("Аня", "привет") == "Привет, Аня!"
    assert core.calls == [("text", "привет", "Аня")]


async def test_voice_goes_to_core_as_audio() -> None:
    core = FakeCore("Слышу")
    assert await assistant(core).voice("Аня", b"OggS") == "Слышу"
    assert core.calls == [("voice", b"OggS", "Аня")]


async def test_photo_with_barcode_and_caption() -> None:
    core = FakeCore("Записано")
    reply = await assistant(core, barcode="4601234567893").photo("Аня", b"jpeg", " 200 г ")
    assert reply == "Записано"
    assert core.calls == [("text", "штрихкод 4601234567893, 200 г", "Аня")]


async def test_photo_with_barcode_without_caption() -> None:
    core = FakeCore()
    await assistant(core, barcode="96385074").photo("Аня", b"jpeg", None)
    assert core.calls == [("text", "штрихкод 96385074", "Аня")]


async def test_photo_without_barcode_does_not_bother_core() -> None:
    core = FakeCore()
    reply = await assistant(core, barcode=None).photo("Аня", b"jpeg", "200 г")
    assert reply == NO_BARCODE == "Не вижу штрихкод на фото. Сфотографируй его ближе."
    assert core.calls == []


@pytest.mark.parametrize(
    ("error", "reply"),
    [
        (CoreUnavailableError("down"), CORE_UNAVAILABLE),
        (CoreUnauthorizedError("401"), CORE_UNAUTHORIZED),
        (CoreRejectedError("422"), CORE_REJECTED),
    ],
)
async def test_core_errors_become_replies(error: CoreError, reply: str) -> None:
    bot = assistant(FakeCore(error=error), barcode="4601234567893")
    assert await bot.text("Аня", "привет") == reply
    assert await bot.voice("Аня", b"OggS") == reply
    assert await bot.photo("Аня", b"jpeg", None) == reply


def test_reply_texts() -> None:
    assert CORE_UNAVAILABLE == "Кузя сейчас недоступен."
    assert CORE_UNAUTHORIZED == "Кузя не пускает бота — проверь токен."


async def test_unauthorized_is_logged_as_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        await assistant(FakeCore(error=CoreUnauthorizedError("401"))).text("Аня", "секрет")
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "токен" in errors[0].getMessage()
    assert "секрет" not in caplog.text


async def test_empty_answer_gets_a_placeholder() -> None:
    assert await assistant(FakeCore("  ")).text("Аня", "привет") == CORE_EMPTY
