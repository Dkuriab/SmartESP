"""Тесты разбора русских названий: нормализация, окончания, количество в тексте."""

import pytest

from food_mcp.names import Amount, parse_amount, stem, tokens


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("гречка", "гречк"),
        ("гречку", "гречк"),
        ("гречки", "гречк"),
        ("гречкой", "гречк"),
        ("варёная", "варен"),
        ("варёную", "варен"),
        ("варёный", "варен"),
        ("яйцо", "яйц"),
        ("яйца", "яйц"),
        ("сыр", "сыр"),
        ("чай", "ча"),
        ("чая", "ча"),
        ("щи", "щи"),
        ("картофеля", "картофел"),
    ],
)
def test_stem(word: str, expected: str) -> None:
    assert stem(word.replace("ё", "е")) == expected


def test_tokens_case_yo_punctuation_order() -> None:
    assert tokens("Гречка (СУХАЯ)") == tokens("сухую гречку")
    assert tokens("Варёная гречка") == tokens("гречка вареная")
    assert tokens("куриная грудка") == tokens("грудку куриную")
    assert tokens("молоко 2,5%") == frozenset({"молок", "2", "5"})


def test_tokens_drop_single_letters() -> None:
    assert tokens("гречка с молоком") == frozenset({"гречк", "молок"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("гречка", Amount("гречка", 0, 0)),
        ("2 яйца", Amount("яйца", 2, 0)),
        ("два яйца", Amount("яйца", 2, 0)),
        ("три штуки яиц", Amount("яиц", 3, 0)),
        ("5 шт. пельменей", Amount("пельменей", 5, 0)),
        ("одно яблоко", Amount("яблоко", 1, 0)),
        ("гречка 150 г", Amount("гречка", 0, 150)),
        ("гречка 62,5 грамма", Amount("гречка", 0, 62.5)),
        ("200 гр творога", Amount("творога", 0, 200)),
        ("  ", Amount("", 0, 0)),
    ],
)
def test_parse_amount(text: str, expected: Amount) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("200 мл молока", Amount("молока", 0, 200)),
        ("молоко 0,5 л", Amount("молоко", 0, 500)),
        ("картошка 1,5 кг", Amount("картошка", 0, 1500)),
    ],
)
def test_parse_amount_other_units(text: str, expected: Amount) -> None:
    assert parse_amount(text) == expected
