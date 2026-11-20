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

# действия по дому и помощника (закрытый список): семейство → (повелительное, «-шь», неопределённая
# форма). Узнай/проверь/расскажи — вопросы о знании, не действие
_ACTIONS: dict[str, tuple[str, str, str]] = {
    "включ": ("включи|включай", "включишь", "включить"),
    "выключ": ("выключи|выключай", "выключишь", "выключить"),
    "постав": ("поставь|ставь", "поставишь", "поставить"),
    "установ": ("установи", "установишь", "установить"),
    "запуст": ("запусти|запускай", "запустишь", "запустить"),
    "останов": ("останови", "остановишь", "остановить"),
    "запис": ("запиши|записывай", "запишешь", "записать"),
    "добав": ("добавь|добавляй", "добавишь", "добавить"),
    "удал": ("удали|удаляй", "удалишь", "удалить"),
    "убр": ("убери|убирай", "уберёшь|уберешь", "убрать"),
    "напомн": ("напомни|напоминай", "напомнишь", "напомнить"),
    "откр": ("открой|открывай", "откроешь", "открыть"),
    "закр": ("закрой|закрывай", "закроешь", "закрыть"),
    "убав": ("убавь", "убавишь", "убавить"),
    "прибав": ("прибавь", "прибавишь", "прибавить"),
    "переключ": ("переключи|переключай", "переключишь", "переключить"),
    "зажг": ("зажги", "зажжёшь|зажжешь", "зажечь"),
    "погас": ("погаси", "погасишь", "погасить"),
}
_ASKED = {
    family: re.compile(rf"\b(?:(?:{imp})(?:те)?|{fut})\b", re.IGNORECASE)
    for family, (imp, fut, _inf) in _ACTIONS.items()
}
_INFINITIVES = {
    family: re.compile(rf"\b{inf}\b", re.IGNORECASE) for family, (_i, _f, inf) in _ACTIONS.items()
}
# состояние (краткое причастие) по группам синонимов просьбы: «Поставь будильник» → «установлен»,
# «Запиши обед» → «добавлен», «Включи музыку» → «запущена»
_STATES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = tuple(
    (frozenset(families.split()), re.compile(rf"\b(?:{forms})[аоы]?\b", re.IGNORECASE))
    for families, forms in (
        ("постав установ запуст", "поставлен|установлен|запущен|завед[её]н"),
        ("запис добав", "записан|добавлен|внес[её]н|сохран[её]н|отмечен"),
        ("включ зажг", "включ[её]н|зажж[её]н|запущен"),
        ("выключ погас останов", "выключ[её]н|погаш[её]н|отключ[её]н|остановлен"),
        ("удал убр", "удал[её]н|убран|ст[её]рт"),
        ("напомн", "поставлен|создан|установлен"),
        ("откр", "открыт"),
        ("закр", "закрыт"),
        ("переключ", "переключ[её]н"),
    )
)
# «можешь включить», «могла бы поставить», «надо записать» — но не «можно ли …», «нужно ли …»
_MODAL = re.compile(
    r"\b(?:можешь|можете|можно|нужно|надо|хочу|пожалуйста|мог(?:ла|ли)?\s+бы|хотел[аи]?\s+бы)\b(?!\s+ли\b)",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|„[^“]*“")
_FILLER = frozenset("ты вы мне нам бы пожалуйста".split())  # между модальным словом и действием
_KNOWLEDGE = frozenset("как почему зачем когда где сколько кто какой какая какие что".split())

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
# рассказ о прошлом или возможном: «был запущен», «может быть установлен», год «1957», «в 2009 году»
_HISTORIC = re.compile(
    r"\b(?:был[аои]?|будет|будут|быть)\b|\b(?:1\d{3}|20\d{2})\b|\bгод[ау]?\b|\bвек[еа]?\b", re.IGNORECASE
)
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


def requested_actions(question: str) -> frozenset[str]:
    """Семейства действий, о которых просит человек: «Включи свет», «Включишь свет?», «Можешь
    поставить таймер?», «Включить свет». Цитаты («как сказать «включи»?») не считаются."""
    text = _QUOTED.sub(" ", question)
    words = text.lower().split()
    if words and words[0].strip(",.!?") in _KNOWLEDGE:
        return frozenset()  # «Как можно установить…», «Когда включают…» — вопрос о знании
    found = {family for family, pattern in _ASKED.items() if pattern.search(text)}
    for family, pattern in _INFINITIVES.items():
        match = pattern.search(text)
        if match and (pattern.match(text.lstrip()) or _modal_before(text[: match.start()])):
            found.add(family)  # неопределённая форма в начале или сразу после «можешь/надо…»
    return frozenset(found)


def _modal_before(text: str) -> bool:
    """True, если текст кончается модальным словом («можешь», «могла бы»…) и, может быть, «ты/мне/бы»."""
    modals = list(_MODAL.finditer(text))
    if not modals:
        return False
    between = re.sub(r"[,.!?]", " ", text[modals[-1].end() :]).lower().split()
    return all(word in _FILLER for word in between)


def asks_action(question: str) -> bool:
    """True, если человек просит действие из закрытого списка (не вопрос о знании)."""
    return bool(requested_actions(question))


def false_claim(sentence: str, question: str, after_tools: bool = False) -> bool:
    """True, если на просьбу question первое предложение утверждает, что действие сделано.

    after_tools — прошлый ход был с вызовом инструмента: «Да, …» и «уже …» тогда — подтверждение.
    """
    families = requested_actions(question)
    if not families or not claims_action(sentence, families):
        return False
    return not (after_tools and _CONFIRM.search(sentence))


def claims_action(sentence: str, families: frozenset[str] | None = None) -> bool:
    """True, если предложение голосом помощника утверждает, что действие сделано или делается.

    Вопрос («…?»), отрицание («не включила»), условное («записала бы»), чужое лицо
    («ты поставил») и рассказ о прошлом («был запущен в 1957 году») — не утверждение.
    Краткое причастие («Свет включён») — только у семейств families (просьба этого хода;
    None — любое семейство).
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
    states = [p for group, p in _STATES if families is None or group & families]
    return any(not _hedged(sentence, m.start(), m.end()) for p in states for m in p.finditer(sentence))


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
