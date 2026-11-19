"""Тесты нарезки ответа на предложения и чистки текста для озвучки."""

from collections.abc import AsyncIterator

import pytest

from smartesp.contracts import ReplyPart
from smartesp.conversation import clean_for_speech, is_meaningless, split_sentences


async def _parts(*texts: str) -> AsyncIterator[ReplyPart]:
    for text in texts:
        yield ReplyPart(text)


async def _split(*texts: str) -> list[str]:
    return [s async for s in split_sentences(_parts(*texts))]


async def test_short_sentence_is_glued_to_next() -> None:
    out = await _split("Привет! Сегодня", " солнечно и тепло. Хорошего", " дня")
    assert out == ["Привет! Сегодня солнечно и тепло.", "Хорошего дня"]


async def test_newline_ends_sentence() -> None:
    out = await _split("Первая строка списка покупок\nВторая строка")
    assert out == ["Первая строка списка покупок", "Вторая строка"]


async def test_newline_ends_short_sentence_too() -> None:
    # короткая фраза перед вызовом инструмента звучит сразу, а не ждёт следующей
    sentences = split_sentences(_parts("Записываю.\n", "Готово, хлеб в списке покупок."))
    assert await anext(sentences) == "Записываю."
    assert [s async for s in sentences] == ["Готово, хлеб в списке покупок."]


async def test_empty_lines_give_no_sentences() -> None:
    assert await _split("Да.\n\n\nНет") == ["Да.", "Нет"]


async def test_dot_without_space_is_not_a_boundary() -> None:
    # «3.5» не режется, а точка в конце куска ждёт следующего куска
    out = await _split("Температура сейчас 3.", "5 градусов. Ветер слабый, без осадков.")
    assert out == ["Температура сейчас 3.5 градусов.", "Ветер слабый, без осадков."]


async def test_sentence_is_yielded_before_stream_ends() -> None:
    parts = _parts("Это достаточно длинное предложение. И ещё")
    sentences = split_sentences(parts)
    assert await anext(sentences) == "Это достаточно длинное предложение."


async def test_empty_stream_gives_nothing() -> None:
    assert await _split() == []
    assert await _split("  ", "\n") == []


def test_clean_for_speech() -> None:
    assert clean_for_speech("**Ответ:** - один") == "Ответ: один"
    assert clean_for_speech("# Список\n- хлеб\n* молоко\n• `сыр`") == "Список\nхлеб\nмолоко\nсыр"
    assert clean_for_speech("Минус -5 градусов") == "Минус -5 градусов"


def test_clean_for_speech_keeps_dashes_and_reads_multiplication() -> None:
    text = "Москва - столица России, 5 - 3 = 2, 2*3=6"
    assert clean_for_speech(text) == "Москва - столица России, 5 - 3 = 2, 2 на 3=6"
    assert clean_for_speech("Итого: 4 * 5 = 20") == "Итого: 4 на 5 = 20"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "а",
        "...",
        "Продолжение следует...",
        "...Продолжение следует",
        "субтитры сделал DimaTorzok",
        "«Субтитры сделал DimaTorzok»",
        " - Спасибо за просмотр!",
    ],
)
def test_meaningless(text: str) -> None:
    assert is_meaningless(text)


@pytest.mark.parametrize("text", ["Который час?", "да", "Редкие субтитры"])
def test_meaningful(text: str) -> None:
    assert not is_meaningless(text)
