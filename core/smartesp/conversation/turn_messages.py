"""Сообщения завершённого хода для истории: вызовы инструментов и передачи записываются вызовами."""

import itertools

from smartesp.contracts import DELEGATE_TOOL, ChatMessage, ToolCall

from .sentences import strip_style_tag
from .turn import Turn, answer_text, history_question

# столько символов ответа инструмента остаётся в истории; длиннее — обрезается с «…»
HISTORY_RESULT_CHARS = 600


def _segments(turn: Turn) -> list[str]:
    """Тексты исполнителей хода по порядку: входной, затем цель каждой передачи."""
    bounds = [0, *turn.breaks, len(turn.answer)]
    return [strip_style_tag("".join(turn.answer[a:b]))[1].strip() for a, b in itertools.pairwise(bounds)]


def _clip(text: str) -> str:
    """Ответ инструмента для истории: не длиннее HISTORY_RESULT_CHARS (с «…» в конце)."""
    if len(text) <= HISTORY_RESULT_CHARS:
        return text
    return text[: HISTORY_RESULT_CHARS - 1].rstrip() + "…"


def _tool_messages(turn: Turn) -> list[ChatMessage]:
    """Вызовы инструментов входного исполнителя по порядку: assistant с вызовом и tool с ответом.

    Вызовы целей передачи сюда не входят: история — диалог входного, а сказанное
    целью уже стоит в ответе delegate.
    """
    entry = turn.path[0] if turn.path else ""
    messages: list[ChatMessage] = []
    for exchange in turn.exchanges:
        if exchange.executor != entry:
            continue
        messages.append(ChatMessage("assistant", "", tool_calls=(exchange.call,)))
        messages.append(ChatMessage("tool", _clip(exchange.result), tool_name=exchange.call.name))
    return messages


def turn_messages(turn: Turn) -> list[ChatMessage]:
    """Сообщения хода: вопрос, вызовы инструментов входного исполнителя, затем ответ.

    Без передачи — assistant с полным текстом ответа. С передачей диспетчер сам
    вызвал delegate один раз (первую передачу): фраза до неё и вызов — в assistant,
    всё, что сказали цели (и вложенные тоже), через пробел — в tool. Если куски
    ответа не сходятся с передачами — assistant с полным текстом.
    """
    head = [ChatMessage("user", history_question(turn)), *_tool_messages(turn)]
    segments = _segments(turn)
    if not turn.delegations or len(segments) != len(turn.delegations) + 1:
        return [*head, ChatMessage("assistant", answer_text(turn))]
    first = turn.delegations[0]
    call = ToolCall(DELEGATE_TOOL, {"executor": first.target, "task": first.task})
    targets_said = " ".join(text for text in segments[1:] if text)
    return [
        *head,
        ChatMessage("assistant", segments[0], tool_calls=(call,)),
        ChatMessage("tool", targets_said, tool_name=DELEGATE_TOOL),
    ]
