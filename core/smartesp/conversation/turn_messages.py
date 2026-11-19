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
    """Сообщения хода: вопрос и ответ; при передачах — assistant с вызовом delegate и ответ tool.

    На каждую передачу по паре assistant (фраза до неё; у вложенной — пустой текст)
    и tool (то, что сказала цель). Если куски ответа не сходятся с передачами —
    обычная пара user/assistant с полным текстом.
    """
    user = ChatMessage("user", turn.text)
    segments = _segments(turn)
    if not turn.delegations or len(segments) != len(turn.delegations) + 1:
        return [user, ChatMessage("assistant", answer_text(turn))]
    messages = [user]
    for index, handoff in enumerate(turn.delegations):
        call = ToolCall(DELEGATE_TOOL, {"executor": handoff.target, "task": handoff.task})
        said = segments[index] if index == 0 else ""
        messages.append(ChatMessage("assistant", said, tool_calls=(call,)))
        messages.append(ChatMessage("tool", segments[index + 1], tool_name=DELEGATE_TOOL))
    return messages
