"""Конец разговора: прощание узнаётся до модели, вопрос-предложение помощи не звучит."""

import pytest

from smartesp.conversation.farewell import is_farewell
from smartesp.conversation.sentences import drop_offer


@pytest.mark.parametrize(
    "text",
    [
        "Всё, пока",
        "Пока!",
        "Спасибо, хватит",
        "Спокойной ночи",
        "Ну всё, спасибо",
        "Больше ничего не нужно",
        "Отбой",
    ],
)
def test_farewell(text: str) -> None:
    assert is_farewell(text)


@pytest.mark.parametrize(
    "text",
    [
        "Спасибо",
        "Хорошо",
        "Всё понятно, а сколько стоит хлеб?",
        "Пока не надо включать свет",
        "Добавь всё в список",
        "",
    ],
)
def test_not_farewell(text: str) -> None:
    assert not is_farewell(text)


async def test_farewell_turn_is_silent_without_model_or_listen() -> None:
    from conversation_helpers import Setup
    from test_listen_after import finish_turn

    from fakes.fake_events import RecordingSink
    from fakes.fake_executor import FakeExecutor
    from fakes.fake_stt import FakeSTT

    sink = RecordingSink()
    executor = FakeExecutor(["Было приятно поболтать! Чем ещё помочь?"])
    setup = Setup(executor, stt=FakeSTT("Всё, пока"), events=sink)
    finished = await finish_turn(setup, sink)
    assert executor.calls == []  # модель не спрашивали
    assert setup.port.listen_afters == []  # и колонка не слушает
    assert finished["status"] == "ok" and finished["answer"] == ""
    assert setup.history.messages() == []


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Привет! Как могу помочь?", "Привет!"),
        ("Таймер поставила. Чем ещё могу помочь?", "Таймер поставила."),
        ("Готово. Что-нибудь ещё?", "Готово."),
        ("Записала. Могу ли я ещё чем-то быть полезна?", "Записала."),
        ("Чем могу помочь?", ""),
        (
            "Какой таймер поставить: на пять или на десять минут?",
            "Какой таймер поставить: на пять или на десять минут?",
        ),
        ("Сейчас плюс три. Взять зонт?", "Сейчас плюс три. Взять зонт?"),
    ],
)
def test_offer_question_is_dropped(text: str, kept: str) -> None:
    assert drop_offer(text) == kept
