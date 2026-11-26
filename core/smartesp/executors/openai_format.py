"""Формат OpenAI chat/completions: диалог и инструменты в запросе, куски потока SSE, текст ошибки."""

import json
from collections.abc import Sequence
from typing import Any, cast

from smartesp.contracts import ChatMessage, ReplyPart, ToolCall, ToolSpec

DONE = "data: [DONE]"  # конец потока SSE


def tool_payload(tool: ToolSpec) -> dict[str, Any]:
    """Инструмент в формате tools OpenAI."""
    function = {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
    return {"type": "function", "function": function}


def _take_call(pending: list[tuple[str, str]], name: str) -> str | None:
    """id ожидающего вызова с этим именем (иначе первого); нет ожидающих — None."""
    for index, (_, call_name) in enumerate(pending):
        if call_name == name:
            return pending.pop(index)[0]
    return pending.pop(0)[0] if pending else None


def messages_payload(system_prompt: str, messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Диалог в формате OpenAI: вызовам инструментов даются id, ответы инструментов ссылаются на них.

    Ответ инструмента без вызова перед ним (так история не бывает, но вдруг) — сообщение user
    с текстом ответа: API отклонил бы tool без tool_call_id.
    """
    payload: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    pending: list[tuple[str, str]] = []
    for i, message in enumerate(messages):
        if message.role == "assistant" and message.tool_calls:
            ids = [f"call_{i}_{j}" for j in range(len(message.tool_calls))]
            pending = [(call_id, c.name) for call_id, c in zip(ids, message.tool_calls, strict=True)]
            calls = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                }
                for call_id, c in zip(ids, message.tool_calls, strict=True)
            ]
            payload.append({"role": "assistant", "content": message.content or None, "tool_calls": calls})
        elif message.role == "tool":
            call_id = _take_call(pending, message.tool_name)
            if call_id is None:
                payload.append(
                    {"role": "user", "content": f"Ответ инструмента {message.tool_name}: {message.content}"}
                )
            else:
                payload.append({"role": "tool", "tool_call_id": call_id, "content": message.content})
        else:
            payload.append({"role": message.role, "content": message.content})
    return payload


def _arguments(raw: object) -> dict[str, object]:
    """Аргументы вызова: JSON-строка или словарь; неразборчивое — пустой словарь."""
    if isinstance(raw, dict):
        return cast(dict[str, object], raw)
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else {}


def error_detail(body: bytes) -> str:
    """Текст ошибки из тела ответа {"error": {"message": …}} (или {"error": "…"}) или начало тела."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body[:200].decode("utf-8", "replace").strip()
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, str) and error:
        return error
    message = error.get("message") if isinstance(error, dict) else None
    return str(message) if message else str(data)[:200]


def sse_chunk(line: str) -> dict[str, Any] | None:
    """Кусок из строки SSE «data: {…}»; служебные строки, [DONE] и неразборчивое — None."""
    if not line.startswith("data:") or line.strip() == DONE:
        return None  # «: OPENROUTER PROCESSING» и пустые строки — служебные
    try:
        chunk = json.loads(line[5:])
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], chunk) if isinstance(chunk, dict) else None


class ToolCallParts:
    """Вызовы инструментов, собранные из кусков потока (по index: имя и части аргументов)."""

    def __init__(self) -> None:
        self._slots: dict[int, list[str]] = {}

    def add(self, delta: dict[str, Any]) -> None:
        """Добавляет части вызовов из delta.tool_calls."""
        for raw in delta.get("tool_calls") or []:
            call = cast(dict[str, Any], raw)
            slot = self._slots.setdefault(int(call.get("index") or 0), ["", ""])
            function = cast(dict[str, Any], call.get("function") or {})
            if function.get("name") and not slot[0]:
                slot[0] = str(function["name"])
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                slot[1] = json.dumps(arguments)
            elif arguments:
                slot[1] += str(arguments)

    def parts(self) -> list[ReplyPart]:
        """Готовые вызовы по порядку; без имени — пропускаются."""
        return [
            ReplyPart(tool_call=ToolCall(name, _arguments(args)))
            for name, args in (self._slots[i] for i in sorted(self._slots))
            if name
        ]
