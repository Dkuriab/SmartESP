"""Речь: короткий итог ответа Claude без разметки и длительности словами."""

import math
import re

# Формы слов: (одна, две-четыре, пять и больше); у минут винительный отличается.
_HOUR = ("час", "часа", "часов")
_MINUTE = ("минута", "минуты", "минут")
_MINUTE_ACC = ("минуту", "минуты", "минут")

_FENCE = re.compile(r"```.*?(```|\Z)", re.DOTALL)
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_LINE_MARK = re.compile(r"^\s*(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)")
_TABLE_RULE = re.compile(r"^[\s|:-]+$")
_EMPHASIS = re.compile(r"\*\*|__|\*|`")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_SPACE_BEFORE_MARK = re.compile(r"\s+([.,;:!?…])")
_TERMINAL = ".!?…"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Число со словом в нужной форме: 1 минута, 2 минуты, 5 минут."""
    tail = n % 100
    if 11 <= tail <= 14:
        form = forms[2]
    elif tail % 10 == 1:
        form = forms[0]
    elif 2 <= tail % 10 <= 4:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n} {form}"


def duration(seconds: float, accusative: bool = False) -> str:
    """Длительность словами с точностью до минуты: «меньше минуты», «1 час 21 минута».

    `accusative` — форма после «в»/«за»: «в 1 минуту».
    """
    minutes_total = math.floor(max(0.0, seconds) / 60)
    if minutes_total == 0:
        return "меньше минуты"
    hours, minutes = divmod(minutes_total, 60)
    minute_forms = _MINUTE_ACC if accusative else _MINUTE
    parts = ([plural(hours, _HOUR)] if hours else []) + ([plural(minutes, minute_forms)] if minutes else [])
    return " ".join(parts)


def sentence_end(text: str) -> str:
    """Текст с точкой в конце, если там ещё нет знака конца предложения."""
    text = text.strip()
    if not text or text[-1] in _TERMINAL:
        return text
    return text + "."


def _plain_lines(text: str) -> list[str]:
    """Строки текста без кода, ссылок и разметки Markdown; пустые выброшены."""
    text = _FENCE.sub("\n", text)
    text = _IMAGE_OR_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    lines: list[str] = []
    for raw in text.splitlines():
        if _TABLE_RULE.match(raw):
            continue
        line = _EMPHASIS.sub("", _LINE_MARK.sub("", raw)).replace("|", " ")
        line = _SPACE_BEFORE_MARK.sub(r"\1", " ".join(line.split())).strip(" :;,")
        if line:
            lines.append(line[0].upper() + line[1:])
    return lines


def summarize(text: str, sentences: int, max_chars: int = 300) -> str:
    """Первые `sentences` предложений ответа для озвучки: без разметки, не длиннее `max_chars`.

    Каждая строка (заголовок, пункт списка) считается отдельным предложением.
    """
    plain = " ".join(sentence_end(line) for line in _plain_lines(text))
    parts = [p for p in _SENTENCE_END.split(plain) if p]
    result = " ".join(parts[:sentences])
    if len(result) > max_chars:
        cut = result[:max_chars].rsplit(" ", 1)[0]
        result = cut.rstrip(" ,;:") + "…"
    return result
