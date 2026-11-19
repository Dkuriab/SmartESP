"""Сообщения завершённого хода для истории: передачи записываются вызовом инструмента."""

import itertools

from smartesp.contracts import DELEGATE_TOOL, ChatMessage, ToolCall

from .sentences import strip_style_tag
from .turn import Turn, answer_text


def _segments(turn: Turn) -> list[str]:
    """Тексты исполнителей хода по порядку: входной, затем цель каждой передачи."""
    bounds = [0, *turn.breaks, len(turn.answer)]
    return [strip_style_tag("".join(turn.answer[a:b]))[1].strip() for a, b in itertools.pairwise(bounds)]


def turn_messages(turn: Turn) -> list[ChatMessage]:
    """Сообщения хода: вопрос и ответ; с передачей — assistant с вызовом delegate и ответ tool.

    Диспетчер сам вызвал delegate один раз (первую передачу): фраза до неё и вызов —
    в assistant, всё, что сказали цели (и вложенные тоже), через пробел — в tool.
    Если куски ответа не сходятся с передачами — обычная пара user/assistant с
    полным текстом.
    """
    user = ChatMessage("user", turn.text)
    segments = _segments(turn)
    if not turn.delegations or len(segments) != len(turn.delegations) + 1:
        return [user, ChatMessage("assistant", answer_text(turn))]
    first = turn.delegations[0]
    call = ToolCall(DELEGATE_TOOL, {"executor": first.target, "task": first.task})
    targets_said = " ".join(text for text in segments[1:] if text)
    return [
        user,
        ChatMessage("assistant", segments[0], tool_calls=(call,)),
        ChatMessage("tool", targets_said, tool_name=DELEGATE_TOOL),
    ]
