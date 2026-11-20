"""Тесты flatten и того, что видят участники: передачи — плоско, вызовы коннекторов — если умеет."""

from network_helpers import call, collect, network

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage, ToolCall
from smartesp.network.dialog import after_tools, flatten, request

NOTE_CALL = ChatMessage("assistant", "", tool_calls=(ToolCall("list_add", {"items": ["хлеб"]}),))
NOTE_RESULT = ChatMessage("tool", "Добавила: хлеб.", tool_name="list_add")
DELEGATE_CALL = ChatMessage("assistant", "Минутку.", tool_calls=(ToolCall("delegate", {"executor": "big"}),))
DELEGATE_RESULT = ChatMessage("tool", "Ответ большой.", tool_name="delegate")
HISTORY = [
    ChatMessage("user", "Добавь хлеб"),
    NOTE_CALL,
    NOTE_RESULT,
    ChatMessage("assistant", "Добавила."),
    ChatMessage("user", "Расскажи"),
    DELEGATE_CALL,
    DELEGATE_RESULT,
]


def test_without_keep_tools_connector_calls_are_dropped_and_delegate_is_plain() -> None:
    assert flatten(HISTORY) == [
        ChatMessage("user", "Добавь хлеб"),
        ChatMessage("assistant", "Добавила."),
        ChatMessage("user", "Расскажи"),
        ChatMessage("assistant", "Минутку. Ответ большой."),
    ]


def test_keep_tools_keeps_connector_calls_as_they_are() -> None:
    assert flatten(HISTORY, keep_tools=True) == [
        ChatMessage("user", "Добавь хлеб"),
        NOTE_CALL,
        NOTE_RESULT,
        ChatMessage("assistant", "Добавила."),
        ChatMessage("user", "Расскажи"),
        ChatMessage("assistant", "Минутку. Ответ большой."),
    ]


def test_answer_is_not_glued_to_a_kept_call() -> None:
    messages = [ChatMessage("user", "В"), NOTE_CALL, ChatMessage("assistant", "Готово.")]
    assert flatten(messages, keep_tools=True) == messages


def test_flatten_twice_without_tools_strips_what_keep_tools_kept() -> None:
    assert flatten(flatten(HISTORY, keep_tools=True)) == flatten(HISTORY)


ASKED = [*HISTORY[:4], ChatMessage("user", "Что в списке?")]


async def test_entry_without_targets_still_sees_its_tool_calls() -> None:
    entry = FakeExecutor(["Хлеб."])
    await collect(network(entry, targets=()), ASKED)
    assert entry.calls[0][1:3] == [NOTE_CALL, NOTE_RESULT]


async def test_entry_without_tools_does_not_see_tool_calls() -> None:
    entry = FakeExecutor(["Хлеб."])
    await collect(network(entry, targets=(), tools_ok=False), ASKED)
    assert NOTE_CALL not in entry.calls[0] and NOTE_RESULT not in entry.calls[0]


async def test_target_with_tools_sees_tool_calls_of_history() -> None:
    big = FakeExecutor(["Хлеб."])
    await collect(network(FakeExecutor([call()]), big), ASKED)
    assert big.calls[0][1:3] == [NOTE_CALL, NOTE_RESULT]


def _turn(user: str, answer: str, tool: str = "") -> list[ChatMessage]:
    calls = (ToolCall(tool, {}),) if tool else ()
    exchange = [ChatMessage("assistant", "", tool_calls=calls), ChatMessage("tool", "ок", tool_name=tool)]
    return [ChatMessage("user", user), *(exchange if tool else []), ChatMessage("assistant", answer)]


def test_after_tools_counts_connector_calls_but_not_delegate() -> None:
    now = [ChatMessage("user", "Включи музыку")]
    assert after_tools([*_turn("Поставь таймер", "Готово.", "timer_start"), *now])
    assert not after_tools([*_turn("Почему пал Рим?", "Рим пал…", "delegate"), *now])
    assert not after_tools([*_turn("Привет", "Привет!"), *now])
    assert not after_tools(now)


def test_short_answer_to_a_clarification_carries_the_previous_request() -> None:
    history = _turn("Запиши обед: гречка 150 грамм", "Уточни: гречка сухая или варёная?", "food_log")
    assert request([*history, ChatMessage("user", "Варёная")]) == "Запиши обед: гречка 150 грамм\nВарёная"
    long = "А вообще расскажи мне про гречку подробнее"
    assert request([*history, ChatMessage("user", long)]) == long  # не короткий ответ — новая тема
    plain = _turn("Запиши обед", "Записала.", "food_log")
    assert request([*plain, ChatMessage("user", "Спасибо")]) == "Спасибо"  # не было уточнения
    assert request([*history, ChatMessage("user", "")]) == ""  # пустой вопрос остаётся пустым
