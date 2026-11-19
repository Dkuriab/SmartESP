"""Тесты сообщений хода для истории."""

from smartesp.contracts import ChatMessage, Handoff, ToolCall, Utterance
from smartesp.conversation.turn import ToolExchange, Turn
from smartesp.conversation.turn_messages import HISTORY_RESULT_CHARS, turn_messages


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


def test_nested_handoffs_give_dispatcher_one_pair_with_all_target_text() -> None:
    handoffs = [Handoff("a", "b", "Б", "t1"), Handoff("b", "c", "Ц", "t2")]
    turn = make_turn(["Минутку.", "Спрошу.", "Итог."], [1, 2], handoffs)
    assert turn_messages(turn) == [
        ChatMessage("user", "Вопрос"),
        ChatMessage("assistant", "Минутку.", tool_calls=(call("b", "t1"),)),
        ChatMessage("tool", "Спрошу. Итог.", tool_name="delegate"),
    ]


def test_mismatched_segments_fall_back_to_plain_pair() -> None:
    turn = make_turn(["А.", "Б."], [1], [])
    assert turn_messages(turn)[1] == ChatMessage("assistant", "А. Б.")


def exchange(executor: str, name: str, result: str) -> ToolExchange:
    return ToolExchange(executor, ToolCall(name, {"what": "гречка"}), result)


def test_entry_tool_calls_go_before_the_answer() -> None:
    turn = make_turn(["Записала."], [], [])
    turn.path = ["dispatcher"]
    turn.exchanges = [exchange("dispatcher", "food_log", "Уточни: сухая или варёная?")]
    assert turn_messages(turn) == [
        ChatMessage("user", "Вопрос"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("food_log", {"what": "гречка"}),)),
        ChatMessage("tool", "Уточни: сухая или варёная?", tool_name="food_log"),
        ChatMessage("assistant", "Записала."),
    ]


def test_entry_tool_calls_go_before_delegate_and_target_calls_are_left_out() -> None:
    turn = make_turn(["Минутку.", "Ответ."], [1], [Handoff("dispatcher", "big", "Большая", "задача")])
    turn.path = ["dispatcher", "big"]
    turn.exchanges = [exchange("dispatcher", "notes_show", "покупки: хлеб"), exchange("big", "calc", "4")]
    messages = turn_messages(turn)
    assert [(m.role, m.tool_name) for m in messages] == [
        ("user", ""),
        ("assistant", ""),
        ("tool", "notes_show"),
        ("assistant", ""),
        ("tool", "delegate"),
    ]
    assert messages[3].tool_calls == (call("big", "задача"),)
    assert messages[4].content == "Ответ."


def test_long_tool_result_is_clipped() -> None:
    turn = make_turn(["Вот."], [], [])
    turn.path = ["dispatcher"]
    turn.exchanges = [exchange("dispatcher", "notes_find", "а" * 2000)]
    clipped = turn_messages(turn)[2].content
    assert len(clipped) == HISTORY_RESULT_CHARS and clipped.endswith("…")


def test_short_tool_result_is_kept_whole() -> None:
    turn = make_turn(["Вот."], [], [])
    turn.path = ["dispatcher"]
    turn.exchanges = [exchange("dispatcher", "notes_find", "а" * HISTORY_RESULT_CHARS)]
    assert turn_messages(turn)[2].content == "а" * HISTORY_RESULT_CHARS
