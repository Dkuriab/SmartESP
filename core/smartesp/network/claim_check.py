"""Признаки нечестного ответа: утверждение о сделанном действии и вызов инструмента текстом.

Список намеренно короткий и консервативный: лучше пропустить редкую ложь, чем переспрашивать
модель на честных ответах. Ловится только первое предложение (до озвучки). Не ловится:
выдуманные данные без глагола действия («На улице +12°C»), обещание без «сейчас»
(«Поставлю таймер.»), неправда после вызова другого инструмента, ложь во втором предложении.
"""

import re

# конец предложения — как у разговора (conversation.sentences): знак с пробелом после или
# перевод строки; предложения короче FIRST_SENTENCE_CHARS склеиваются со следующим
FIRST_SENTENCE_CHARS = 20
_BOUNDARY = re.compile(r"[.!?…](?=\s)|\n")

# сделано (прошедшее время: «поставил», «поставила», «поставили»)
_DONE = (
    "поставил|записал|включил|выключил|добавил|узнал|проверил|запустил|установил|"
    "сохранил|отправил|удалил|отметил"
)
# сделано (причастие: «включён», «поставлен», «записана»)
_DONE_PASSIVE = "поставлен|записан|включ[её]н|выключ[её]н|добавлен|установлен|запущен|сохран[её]н"
# делаю прямо сейчас
_NOW = "включаю|выключаю|ставлю|записываю|добавляю|запускаю|устанавливаю|сохраняю"
# сделаю — только вместе со «сейчас» в том же предложении («Сейчас включу свет.»)
_SOON = "включу|выключу|поставлю|запишу|добавлю|запущу|установлю|сохраню"

_CLAIM = re.compile(rf"\b(?:(?:{_DONE})(?:а|и|о)?|(?:{_DONE_PASSIVE})(?:а|о|ы)?|{_NOW})\b", re.IGNORECASE)
_LATER = re.compile(rf"\b(?:{_SOON})\b", re.IGNORECASE)
_NOW_WORD = re.compile(r"\bсейчас\b", re.IGNORECASE)
_NEGATION = re.compile(r"\bне\s+$", re.IGNORECASE)  # «не включила»
_CONDITIONAL = re.compile(r"^\s+бы\b", re.IGNORECASE)  # «записала бы»

# вызов текстом: JSON с ключами вызова, служебные метки модели «<|…»
_JSON_CALL = re.compile(r'\{\s*"(?:name|function|tool_calls?|arguments|parameters|executor|task)"\s*:')
_SPECIAL_TOKEN = re.compile(r"<\|")
_STRUCTURE = re.compile(r'\s*(?:\{|\[\s*[{"])')


def first_sentence(text: str) -> str | None:
    """Первое предложение, если оно уже закончено (как его отрежет разговор), иначе None."""
    for match in _BOUNDARY.finditer(text):
        sentence = text[: match.end()].strip()
        if match.group() == "\n" or len(sentence) >= FIRST_SENTENCE_CHARS:
            return sentence
    return None


def claims_action(sentence: str) -> bool:
    """True, если предложение утверждает, что действие сделано, делается или сейчас будет сделано.

    Вопрос («…?»), отрицание («не включила») и условное («записала бы») — не утверждение.
    """
    if sentence.rstrip(" \t\n\"'»)").endswith("?"):
        return False
    for match in _CLAIM.finditer(sentence):
        if not _hedged(sentence, match.start(), match.end()):
            return True
    later = _LATER.search(sentence)
    if later is None or not _NOW_WORD.search(sentence):
        return False
    return not _hedged(sentence, later.start(), later.end())


def spells_tool_call(text: str, names: frozenset[str]) -> bool:
    """True, если в тексте вызов инструмента написан словами: JSON вызова, «имя(…)», метка «<|…»."""
    if _JSON_CALL.search(text) or _SPECIAL_TOKEN.search(text):
        return True
    return any(re.search(rf"\b{re.escape(name)}\s*\(", text) for name in names)


def opens_structure(text: str) -> bool:
    """True, если ответ начинается как JSON («{», «[{», «["», не метка «[style:…]») — читаем дальше."""
    return _STRUCTURE.match(text) is not None


def _hedged(sentence: str, start: int, end: int) -> bool:
    """True, если глагол стоит после «не» или перед «бы»."""
    return bool(_NEGATION.search(sentence[:start]) or _CONDITIONAL.match(sentence[end:]))
