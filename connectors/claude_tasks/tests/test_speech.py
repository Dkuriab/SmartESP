"""Речь: итог ответа Claude в 1–3 предложениях, длительности словами."""

import pytest

from claude_tasks_mcp.speech import duration, sentence_end, summarize


def test_summary_takes_first_sentences() -> None:
    text = "Исправила тест. Добавила проверку. Обновила README. Ещё что-то."
    assert summarize(text, 3) == "Исправила тест. Добавила проверку. Обновила README."
    assert summarize(text, 1) == "Исправила тест."


def test_summary_strips_markdown_and_code() -> None:
    text = (
        "## Итог\n\n"
        "Я **поправила** функцию `parse_time` в файле server.py.\n"
        "```python\nprint('секрет')\n```\n"
        "- первый пункт\n"
        "- второй пункт\n"
        "Подробнее: [документация](https://example.com/doc) и https://example.com.\n"
    )
    assert summarize(text, 3) == "Итог. Я поправила функцию parse_time в файле server.py. Первый пункт."
    assert "print" not in summarize(text, 10)
    assert "http" not in summarize(text, 10)


def test_summary_limits_length() -> None:
    long = "слово " * 200
    result = summarize(long, 3, max_chars=100)
    assert len(result) <= 101
    assert result.endswith("…")


def test_summary_of_empty_text() -> None:
    assert summarize("   \n```\nкод\n```\n", 3) == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [("готово", "готово."), ("готово.", "готово."), ("готово!", "готово!"), ("что?", "что?"), ("", "")],
)
def test_sentence_end(text: str, expected: str) -> None:
    assert sentence_end(text) == expected


@pytest.mark.parametrize(
    ("seconds", "accusative", "expected"),
    [
        (20, False, "меньше минуты"),
        (60, False, "1 минута"),
        (60, True, "1 минуту"),
        (125, False, "2 минуты"),
        (30 * 60, True, "30 минут"),
        (3600 + 21 * 60, False, "1 час 21 минута"),
        (2 * 3600, False, "2 часа"),
    ],
)
def test_duration(seconds: float, accusative: bool, expected: str) -> None:
    assert duration(seconds, accusative=accusative) == expected
