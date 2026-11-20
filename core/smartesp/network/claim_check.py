"""Признаки нечестного ответа: утверждение о сделанном действии и вызов инструмента текстом.

Проверка намеренно осторожная — лучше пропустить редкую ложь, чем переспрашивать модель на
честном ответе. Утверждение ищется, только если человек в этом ходе попросил действие
(«включи», «поставь», «можешь записать…»), и только голосом самого помощника: «Поставила
таймер», «Я записал», «Готово, включаю музыку», «Сейчас включу свет» — или состояние того, что
просили: «Свет на кухне включён» (без «был» и дат: «Спутник был запущен в 1957 году» — факт).
Не ловится: чужое лицо («ты поставил», «они запустили», «Кузя включает»), выдуманные данные без
глагола действия («На улице +12°C»), «Поставлю таймер.» без «сейчас», ложь после вызова другого
инструмента, ложь не в первом предложении; «уже …»/«Да, …» сразу после хода с инструментом —
подтверждение сделанного тогда, а не ложь.
"""

import re

# конец предложения — как у разговора (conversation.sentences): знак с пробелом после или
# перевод строки; предложения короче FIRST_SENTENCE_CHARS склеиваются со следующим
FIRST_SENTENCE_CHARS = 20
_BOUNDARY = re.compile(r"[.!?…](?=\s)|\n")

_VERBS = "постав|запис|включ|выключ|добав|узна|провер|запуст|установ|сохран|отправ|удал|отмет"
# просьба о действии: повелительное («включи», «поставьте») или «можешь/надо …» с неопределённой формой
_IMPERATIVE = re.compile(
    r"\b(?:включи|выключи|поставь|запиши|добавь|запусти|установи|сохрани|отправь|удали|отметь|"
    r"напомни|заведи|проверь|узнай|сделай|убери|закажи|открой|закрой)(?:те)?\b",
    re.IGNORECASE,
)
_POLITE = re.compile(r"\b(?:можешь|можете|можно|нужно|надо|пожалуйста|хочу)\b", re.IGNORECASE)
_INFINITIVE = re.compile(rf"\b(?:{_VERBS})\w*ть\b", re.IGNORECASE)

# голос помощника: прошедшее единственного числа, настоящее первого лица, «сейчас» + будущее
_PAST = re.compile(
    r"\b(?:поставил|записал|включил|выключил|добавил|узнал|проверил|запустил|установил|"
    r"сохранил|отправил|удалил|отметил)а?\b",
    re.IGNORECASE,
)
_PRESENT = re.compile(
    r"\b(?:включаю|выключаю|ставлю|записываю|добавляю|запускаю|устанавливаю|сохраняю)\b", re.IGNORECASE
)
_SOON = re.compile(r"\b(?:включу|выключу|поставлю|запишу|добавлю|запущу|установлю|сохраню)\b", re.IGNORECASE)
# состояние: краткое причастие («включён», «поставлен», «записана»)
_STATE = re.compile(
    r"\b(?:поставлен|записан|включ[её]н|выключ[её]н|добавлен|установлен|запущен|сохран[её]н)[аоы]?\b",
    re.IGNORECASE,
)
_HISTORIC = re.compile(r"\b(?:был[аои]?|будет|будут)\b|\b\d{3,4}\b|\bгод[ау]?\b|\bвек[еа]?\b", re.IGNORECASE)
# слова, после которых глагол — всё ещё голос помощника («Хорошо, я уже поставила…»)
_LEAD = frozenset(
    "я уже только что сейчас хорошо готово ок окей понял поняла понятно да итак так вот всё все ага "
    "конечно отлично сделано ладно есть".split()
)
_CLAUSE = re.compile(r"[.,:;!?—–()\-]")
_STYLE_TAG = re.compile(r"^\s*\[\s*style\s*:\s*[\w-]+\s*\]", re.IGNORECASE)
_NEGATION = re.compile(r"\bне\s+$", re.IGNORECASE)  # «не включила»
_CONDITIONAL = re.compile(r"^\s+бы\b", re.IGNORECASE)  # «записала бы»
_CONFIRM = re.compile(r"^\s*да\b|\bуже\b", re.IGNORECASE)  # «Да, записала», «уже поставлен»

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


def asks_action(question: str) -> bool:
    """True, если человек просит действие: «Включи свет», «Можешь поставить таймер?»."""
    if _IMPERATIVE.search(question):
        return True
    return bool(_POLITE.search(question) and _INFINITIVE.search(question))


def false_claim(sentence: str, question: str, after_tools: bool = False) -> bool:
    """True, если на просьбу question первое предложение утверждает, что действие сделано.

    after_tools — прошлый ход был с вызовом инструмента: «Да, …» и «уже …» тогда — подтверждение.
    """
    if not asks_action(question) or not claims_action(sentence):
        return False
    return not (after_tools and _CONFIRM.search(sentence))


def claims_action(sentence: str) -> bool:
    """True, если предложение голосом помощника утверждает, что действие сделано или делается.

    Вопрос («…?»), отрицание («не включила»), условное («записала бы»), чужое лицо
    («ты поставил») и рассказ о прошлом («был запущен в 1957 году») — не утверждение.
    """
    sentence = _STYLE_TAG.sub("", sentence, count=1)
    if sentence.rstrip(" \t\n\"'»)").endswith("?"):
        return False
    for pattern in (_PAST, _PRESENT):
        if any(_own_voice(sentence, m.start(), m.end()) for m in pattern.finditer(sentence)):
            return True
    soon = [m for m in _SOON.finditer(sentence) if _own_voice(sentence, m.start(), m.end())]
    if soon and re.search(r"\bсейчас\b", sentence[: soon[0].start()], re.IGNORECASE):
        return True
    if _HISTORIC.search(sentence):
        return False
    return any(not _hedged(sentence, m.start(), m.end()) for m in _STATE.finditer(sentence))


def spells_tool_call(text: str, names: frozenset[str]) -> bool:
    """True, если в тексте вызов инструмента написан словами: JSON вызова, «имя(…)», метка «<|…»."""
    if _JSON_CALL.search(text) or _SPECIAL_TOKEN.search(text):
        return True
    return any(re.search(rf"\b{re.escape(name)}\s*\(", text) for name in names)


def opens_structure(text: str) -> bool:
    """True, если ответ начинается как JSON («{», «[{», «["», не метка «[style:…]») — читаем дальше."""
    return _STRUCTURE.match(text) is not None


def _own_voice(sentence: str, start: int, end: int) -> bool:
    """True, если глагол — голос помощника: в своей части предложения после него только вводные слова."""
    if _hedged(sentence, start, end):
        return False
    clause = _CLAUSE.split(sentence[:start])[-1]
    return all(word in _LEAD for word in clause.lower().split())


def _hedged(sentence: str, start: int, end: int) -> bool:
    """True, если глагол стоит после «не» или перед «бы»."""
    return bool(_NEGATION.search(sentence[:start]) or _CONDITIONAL.match(sentence[end:]))
