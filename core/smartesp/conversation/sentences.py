"""Нарезка потока ответа на предложения и подготовка текста к озвучке."""

import re
from collections.abc import AsyncIterator

from smartesp.contracts import ReplyPart

MIN_SENTENCE_CHARS = 20  # короче — склеиваем со следующим, чтобы TTS не «рубил» речь

# Конец предложения: знак, за которым пробел (конец куска ещё не конец текста — «3.5»), или перевод строки.
_BOUNDARY = re.compile(r"[.!?…](?=\s)|\n")
_MULTIPLY = re.compile(r"(?<=\d)[ \t]*\*[ \t]*(?=\d)")  # «2*3» — умножение, а не разметка
_MARKUP = re.compile(r"[*_#`]")
_LIST_MARKER = re.compile(r"^[ \t]*[-+•][ \t]+", re.MULTILINE)
_HYPHEN_AFTER_COLON = re.compile(r"(?<=:)[ \t]*-[ \t]+")  # «Ответ: - один» — список, склеенный в строку
_LEADING_JUNK = re.compile(r"^[\W_]+")  # пробелы, кавычки, многоточия в начале
_SPACES = re.compile(r"[ \t]+")
_STYLE_TAG = re.compile(r"^\s*\[\s*style\s*:\s*([\w-]+)\s*\]\s*", re.IGNORECASE)  # «[style:quiet]»

DEFAULT_STYLE = "normal"

# Известные «галлюцинации» Whisper на тишине и шуме (сравниваем без учёта регистра).
_HALLUCINATIONS = (
    "продолжение следует",
    "субтитры",
    "спасибо за просмотр",
    "редактор субтитров",
)


def _cut(buffer: str) -> tuple[str, str] | None:
    """Ищет первую границу, до которой набралось не меньше MIN_SENTENCE_CHARS.

    Возвращает (предложение, остаток) или None, если резать пока рано.
    """
    for match in _BOUNDARY.finditer(buffer):
        sentence = buffer[: match.end()].strip()
        if len(sentence) >= MIN_SENTENCE_CHARS:
            return sentence, buffer[match.end() :]
    return None


async def split_sentences(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[str]:
    """Режет поток кусков ответа на предложения.

    parts — куски ответа исполнителя. Предложение отдаётся, как только в
    накопленном тексте есть «.», «!», «?», «…» с пробелом после или перевод
    строки и набралось не меньше MIN_SENTENCE_CHARS символов; остаток — в конце.
    Возвращает предложения без пробелов по краям, пустые пропускает.
    """
    buffer = ""
    async for part in parts:
        buffer += part.text
        while (cut := _cut(buffer)) is not None:
            sentence, buffer = cut
            yield sentence
    rest = buffer.strip()
    if rest:
        yield rest


def clean_for_speech(text: str) -> str:
    """Убирает разметку Markdown (* _ # `) и маркеры списков; возвращает текст для TTS.

    Маркер списка — «-», «+», «•» в начале строки или «-» сразу после двоеточия;
    тире и минус внутри фразы остаются. «*» между цифрами читается как «на».
    """
    text = _MULTIPLY.sub(" на ", text)
    text = _MARKUP.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _HYPHEN_AFTER_COLON.sub(" ", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def is_meaningless(text: str) -> bool:
    """Возвращает True, если отвечать не на что: пусто, меньше 2 букв или галлюцинация Whisper."""
    if sum(ch.isalpha() for ch in text) < 2:
        return True
    return _LEADING_JUNK.sub("", text).casefold().startswith(_HALLUCINATIONS)


def strip_style_tag(text: str) -> tuple[str | None, str]:
    """Снимает метку стиля «[style:имя]» с начала текста.

    Возвращает (имя в нижнем регистре или None, текст без метки).
    """
    match = _STYLE_TAG.match(text)
    if not match:
        return None, text
    return match.group(1).lower(), text[match.end() :]


def take_style(text: str, styles: list[str]) -> tuple[str, str]:
    """Стиль озвучки, выбранный моделью меткой в начале ответа, и текст без метки.

    Нет метки или стиль неизвестен озвучке — DEFAULT_STYLE (метка всё равно снимается).
    """
    name, rest = strip_style_tag(text)
    return (name if name in styles else DEFAULT_STYLE), rest
