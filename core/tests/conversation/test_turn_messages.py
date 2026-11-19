"""Тесты сообщений хода для истории."""

from smartesp.contracts import ChatMessage, Handoff, ToolCall, Utterance
from smartesp.conversation.turn import Turn
from smartesp.conversation.turn_messages import turn_messages


def make_turn(answer: list[str], breaks: list[int], handoffs: list[Handoff]) -> Turn:
    turn = Turn(Utterance("fake", 1, b"", 0.0), "fake", 0.0, text="Вопрос")
    turn.answer = answer
    turn.breaks = breaks
    turn.delegations = handoffs
    return turn


def call(target: str, task: str) -> ToolCall:
    return ToolCall("delegate", {"executor": target, "task": task})


def test_turn_without_handoff_is_plain_pair() -> None:
    turn = make_turn(["[style:quiet] Привет."], [], [])
    assert turn_messages(turn) == [ChatMessage("user", "Вопрос"), ChatMessage("assistant", "Привет.")]


def test_handoff_is_tool_call_and_tool_answer() -> None:
    turn = make_turn(["Минутку.", "Вот ", "ответ."], [1], [Handoff("a", "big", "Большая", "задача")])
    assert turn_messages(turn) == [
        ChatMessage("user", "Вопрос"),
        ChatMessage("assistant", "Минутку.", tool_calls=(call("big", "задача"),)),
        ChatMessage("tool", "Вот ответ.", tool_name="delegate"),
    ]


def test_nested_handoffs_give_pair_each_in_order() -> None:
    handoffs = [Handoff("a", "b", "Б", "t1"), Handoff("b", "c", "Ц", "t2")]
    turn = make_turn(["Минутку.", "Спрошу.", "Итог."], [1, 2], handoffs)
    assert turn_messages(turn) == [
        ChatMessage("user", "Вопрос"),
        ChatMessage("assistant", "Минутку.", tool_calls=(call("b", "t1"),)),
        ChatMessage("tool", "Спрошу.", tool_name="delegate"),
        ChatMessage("assistant", "", tool_calls=(call("c", "t2"),)),
        ChatMessage("tool", "Итог.", tool_name="delegate"),
    ]


def test_mismatched_segments_fall_back_to_plain_pair() -> None:
    turn = make_turn(["А.", "Б."], [1], [])
    assert turn_messages(turn)[1] == ChatMessage("assistant", "А. Б.")
