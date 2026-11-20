"""Правило передачи для системного промпта и инструмент delegate."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from smartesp.contracts import DELEGATE_TOOL, ToolSpec

_RULE_HEAD = "Ты можешь передать задачу другим исполнителям. Каждому — свои вопросы:"
_RULE_TAIL = (
    "Если вопрос относится к области одного из исполнителей, сначала скажи одну короткую "
    "фразу (например «Минутку, сейчас узнаю»), затем вызови инструмент delegate с этим "
    "исполнителем; без вызова delegate такую фразу не говори. Если вопрос подходит под условие "
    "исполнителя, обязательно передай его, даже если кажется, что можешь ответить сам. Если "
    "подходят несколько, выбери того, чья область описывает вопрос точнее. Простые вопросы, "
    "приветствия, бытовые просьбы и действия (включить или выключить, записать, поставить "
    "таймер, список, счёт) не передавай: делай сам своими инструментами, а если нужного "
    "инструмента нет — скажи, что нет доступа."
)
# Общее правило, если у участника есть инструменты коннекторов (с целями передачи или без)
TOOLS_RULE = (
    "Для фактов и действий пользуйся инструментами. Говори, что сделал, только если инструмент "
    "вернул успех; если инструмент ответил вопросом — задай этот вопрос человеку (ответ кончается "
    "знаком «?»), если ошибкой — передай её. Если нужного инструмента нет — скажи, что нет "
    "доступа, и ничего не придумывай."
)
_TOOL_DESCRIPTION = "Передать задачу исполнителю, чьё условие точнее всего подходит к вопросу."
_TASK_DESCRIPTION = "Задача своими словами, со всем нужным контекстом"


@dataclass(frozen=True)
class Target:
    """Активная цель передачи.

    id — id исполнителя; name — его имя; when — когда передавать ему (уже с
    подстановкой описания цели, если условие связи пустое).
    """

    id: str
    name: str
    when: str


def _when(target: Target) -> str:
    """Условие без завершающей точки: точку ставит шаблон."""
    return target.when.strip().rstrip(".").rstrip()


def delegate_rule(targets: Sequence[Target]) -> str:
    """Правило передачи для системного промпта; без целей — пустая строка."""
    if not targets:
        return ""
    lines = [f"— {t.name}: {_when(t)}." for t in targets]
    return "\n".join([_RULE_HEAD, *lines, "", _RULE_TAIL])


def delegate_tool(targets: Sequence[Target]) -> ToolSpec:
    """Инструмент delegate: executor — один из id целей, task — задача своими словами."""
    executor: dict[str, object] = {
        "type": "string",
        "enum": [t.id for t in targets],
        "description": "; ".join(f"{t.id} — {t.name}: {_when(t)}" for t in targets),
    }
    task: dict[str, object] = {"type": "string", "description": _TASK_DESCRIPTION}
    parameters: dict[str, object] = {
        "type": "object",
        "properties": {"executor": executor, "task": task},
        "required": ["executor", "task"],
    }
    return ToolSpec(DELEGATE_TOOL, _TOOL_DESCRIPTION, parameters)
