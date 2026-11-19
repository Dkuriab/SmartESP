"""Тесты правила передачи и инструмента delegate."""

from smartesp.network import DELEGATE_TOOL, Target, delegate_rule, delegate_tool

BIG = Target("big", "Большая модель", "сложные вопросы: рассуждения, расчёты")
CODER = Target("coder", "Программист", "вопросы про код")

RULE = (
    "Ты можешь передать задачу другим исполнителям. Каждому — свои вопросы:\n"
    "— Большая модель: сложные вопросы: рассуждения, расчёты.\n"
    "— Программист: вопросы про код.\n"
    "\n"
    "Если вопрос относится к области одного из исполнителей, сначала скажи одну короткую "
    "фразу (например «Минутку, сейчас узнаю»), затем вызови инструмент delegate с этим "
    "исполнителем. Если вопрос подходит под условие исполнителя, обязательно передай его, "
    "даже если кажется, что можешь ответить сам. Если подходят несколько, выбери того, чья "
    "область описывает вопрос точнее. Простые вопросы, приветствия и бытовые просьбы отвечай "
    "сам, без инструмента."
)


def test_rule_with_two_targets_is_exact() -> None:
    assert delegate_rule([BIG, CODER]) == RULE


def test_rule_without_targets_is_empty() -> None:
    assert delegate_rule([]) == ""


def test_rule_does_not_double_final_period() -> None:
    rule = delegate_rule([Target("big", "Большая модель", "знания.")])
    assert "— Большая модель: знания.\n" in rule


def test_tool_lists_targets_in_enum_and_description() -> None:
    tool = delegate_tool([BIG, CODER])
    assert tool.name == DELEGATE_TOOL == "delegate"
    assert tool.description == "Передать задачу исполнителю, чьё условие точнее всего подходит к вопросу."
    params = tool.parameters
    assert params["type"] == "object"
    assert params["required"] == ["executor", "task"]
    props = params["properties"]
    assert isinstance(props, dict)
    assert props["executor"] == {
        "type": "string",
        "enum": ["big", "coder"],
        "description": (
            "big — Большая модель: сложные вопросы: рассуждения, расчёты; "
            "coder — Программист: вопросы про код"
        ),
    }
    assert props["task"] == {
        "type": "string",
        "description": "Задача своими словами, со всем нужным контекстом",
    }


def test_tools_rule_text() -> None:
    from smartesp.network.rules import TOOLS_RULE

    assert (
        TOOLS_RULE
        == "Для фактов пользуйся инструментами; если нужного инструмента нет — скажи, что нет доступа."
    )
    assert TOOLS_RULE not in delegate_rule([BIG])  # добавляется отдельно, один раз
