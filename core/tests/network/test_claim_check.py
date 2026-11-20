"""Тесты распознавания ложных утверждений и вызовов инструментов текстом (страховка честности)."""

import pytest

from smartesp.network.claim_check import claims_action, first_sentence, spells_tool_call

NAMES = frozenset({"timer_start", "delegate", "list_show"})


@pytest.mark.parametrize(
    "text",
    [
        "Поставила таймер на одну минуту.",
        "Поставил таймер на 1 минуту.",
        "Записал обед: 150 грамм гречки.",
        "Свет на кухне включён.",
        "Свет на кухне включен.",
        "Музыка уже включена.",
        "Включаю музыку.",
        "Понял, включаю музыку.",
        "Хорошо, добавила молоко в список.",
        "Узнала: завтра будет дождь.",
        "Проверила, всё в порядке.",
        "Сейчас включу свет на кухне.",
        "Ставлю таймер на пять минут.",
        "Таймер поставлен на пять минут.",
        "[style:quiet] Записала.",
    ],
)
def test_claims_are_caught(text: str) -> None:
    assert claims_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "Я записала бы, но у меня нет такого инструмента.",
        "Я не включила свет: у меня нет доступа к освещению.",
        "Не могу включить свет — нет доступа.",
        "Нет доступа к освещению.",
        "Сейчас 14:37.",
        "Если хочешь, поставлю таймер.",
        "Поставить таймер на пять минут?",
        "Ты уже записал это?",
        "Небо голубое, потому что воздух рассеивает синий свет сильнее.",
        "Привет! Всё хорошо, спасибо.",
        "Минутку, сейчас узнаю.",
        "Сейчас спрошу большую модель.",
        "",
    ],
)
def test_honest_or_neutral_answers_are_not_claims(text: str) -> None:
    assert not claims_action(text)


@pytest.mark.parametrize(
    "text",
    [
        '{ "name": "delegate", "arguments": {"executor": "big", "task": "Рим"} }',
        '{"executor": "big", "task": "Почему пал Рим?"}',
        'timer_start({"seconds": 60})',
        "delegate(executor=big, task=Рим)",
        "<|tool_response>",
        'Минутку. {"name": "list_show"}',
    ],
)
def test_tool_call_spelled_as_text_is_caught(text: str) -> None:
    assert spells_tool_call(text, NAMES)


@pytest.mark.parametrize(
    "text",
    [
        "Таймер на одну минуту запущен через инструмент.",
        "Список покупок: молоко, хлеб.",
        "Функция f(x) растёт.",
        "",
    ],
)
def test_plain_text_is_not_a_tool_call(text: str) -> None:
    assert not spells_tool_call(text, NAMES)


def test_first_sentence_is_cut_like_conversation() -> None:
    assert first_sentence("Поставила") is None
    assert first_sentence("Поставила таймер на минуту.") is None  # без пробела после знака ещё не конец
    assert first_sentence("Поставила таймер на минуту. ") == "Поставила таймер на минуту."
    assert first_sentence("Поставила таймер. ") is None  # короче 20 символов — ждём следующее
    assert first_sentence("Хорошо. Поставила таймер. Ещё") == "Хорошо. Поставила таймер."  # короткое склеено
    assert first_sentence("Записываю\n") == "Записываю"  # перевод строки режет всегда
