"""Нарезка потока ответа на предложения и подготовка текста к озвучке."""

import re
from collections.abc import AsyncIterator

from smartesp.contracts import ReplyPart

MIN_SENTENCE_CHARS = 20  # короче — склеиваем со следующим, чтобы TTS не «рубил» речь

# Конец предложения: знак, за которым пробел (конец куска ещё не конец текста — «3.5»), или перевод строки.
_BOUNDARY = re.compile(r"[.!?…](?=\s)|\n")
_MARKUP = re.compile(r"[*_#`]")
_LIST_MARKER = re.compile(r"^[ \t]*[-+•][ \t]+", re.MULTILINE)
_LONE_HYPHEN = re.compile(r"(?<=\s)-(?=\s)")  # «Ответ: - один» — маркер списка внутри строки
_SPACES = re.compile(r"[ \t]+")

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
    """Убирает разметку Markdown (* _ # `) и маркеры списков; возвращает текст для TTS."""
    text = _MARKUP.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _LONE_HYPHEN.sub("", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def is_meaningless(text: str) -> bool:
    """Возвращает True, если отвечать не на что: пусто, меньше 2 букв или галлюцинация Whisper."""
    if sum(ch.isalpha() for ch in text) < 2:
        return True
    return text.strip().casefold().startswith(_HALLUCINATIONS)
