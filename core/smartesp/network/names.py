"""Поиск имени цели в короткой фразе исполнителя («Сейчас спрошу большую модель.»)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .rules import Target

MAX_PHRASE_CHARS = 80  # фраза длиннее — это уже ответ, а не обещание спросить
_MIN_NAME_WORD = 3  # более короткие слова имени («и», «по») не сравниваются
_WORD = re.compile(r"\w+")
_SENTENCE_END = re.compile(r"[.!?…]")
_EDGE = " \t\n«»\"'"
_LEADING_TAG = re.compile(r"^\s*\[[^\]]*\]")  # метка вроде [style:quiet] в начале ответа


def _words(text: str) -> list[str]:
    """Слова текста без регистра, «ё» как «е»."""
    return _WORD.findall(text.lower().replace("ё", "е"))


def _stem(word: str) -> str:
    """Основа слова: первые max(4, len - 2) символов («программист» → «программи»)."""
    return word[: max(4, len(word) - 2)]


def _is_one_short_sentence(text: str) -> bool:
    """Одно предложение не длиннее MAX_PHRASE_CHARS: знаки конца — только в самом конце."""
    if not text or len(text) > MAX_PHRASE_CHARS:
        return False
    body = text.rstrip(".!?…" + _EDGE)
    return _SENTENCE_END.search(body) is None


def _mentions(phrase: list[str], name: str) -> bool:
    """Каждое слово имени (от 3 букв) своей основой начинает какое-то слово фразы."""
    stems = [_stem(w) for w in _words(name) if len(w) >= _MIN_NAME_WORD]
    return bool(stems) and all(any(p.startswith(s) for p in phrase) for s in stems)


def named_target(text: str, targets: Sequence[Target]) -> Target | None:
    """Цель, которую исполнитель назвал во фразе без вызова инструмента, или None.

    Правило: текст (без метки вроде «[style:quiet]» в начале, без пробелов и
    кавычек по краям) — одно предложение не
    длиннее 80 символов, то есть знаки «. ! ? …» есть только в конце. Сравнение
    без регистра, по основе: каждое слово имени цели длиной от 3 букв своими
    первыми max(4, len - 2) символами начинает какое-то слово фразы
    («большую модель» находит «Большая модель», «программиста» — «Программист»).
    Найдена ровно одна цель — она; ни одной или несколько — None.
    """
    phrase = _LEADING_TAG.sub("", text, count=1).strip(_EDGE)
    if not _is_one_short_sentence(phrase):
        return None
    words = _words(phrase)
    found = [t for t in targets if _mentions(words, t.name)]
    return found[0] if len(found) == 1 else None
