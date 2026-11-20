"""Диалог для цели передачи: плоский, с задачей от диспетчера; вопрос человека; закрытие потоков."""

import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from smartesp.contracts import DELEGATE_TOOL, ChatMessage, ReplyPart

TASK_PREFIX = "\n\nЗадача от диспетчера: "  # дописывается к последнему сообщению user у цели
# строки контекста перед вопросом в сообщении user: так их собирала conversation.build_messages
# до W9 (теперь контекст — отдельное сообщение system); question() по-прежнему их отбрасывает
_NOTE = re.compile(r"^\[[^\]\n]+\] ")  # пометка обработчика «[источник] текст»
_DEVICE = "Колонка: "  # строка с именем колонки
_STYLE_TAG = re.compile(r"^\s*\[\s*style\s*:\s*[\w-]+\s*\]", re.IGNORECASE)  # «[style:quiet]»


@asynccontextmanager
async def closing(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[AsyncIterator[ReplyPart]]:
    """Как contextlib.aclosing, но для любого AsyncIterator: закрывает его, если это генератор."""
    try:
        yield parts
    finally:
        if isinstance(parts, AsyncGenerator):
            await parts.aclose()


def speakable(text: str) -> bool:
    """True, если в тексте есть что озвучить, кроме метки стиля в начале."""
    return any(ch.isalnum() for ch in _STYLE_TAG.sub("", text, count=1))


def question(messages: list[ChatMessage]) -> str:
    """Вопрос человека: последнее сообщение user без пометок обработчиков и строки «Колонка: …».

    Пометки, строка колонки и пустые строки отбрасываются только в начале сообщения.
    Сообщения user нет — пустая строка.
    """
    content = next((m.content for m in reversed(messages) if m.role == "user"), "")
    lines = content.splitlines()
    while lines and (not lines[0].strip() or _NOTE.match(lines[0]) or lines[0].startswith(_DEVICE)):
        lines.pop(0)
    return "\n".join(lines).strip()


FOLLOW_UP_WORDS = 4  # ответ на уточнение помощника: не длиннее стольких слов


def after_tools(messages: list[ChatMessage]) -> bool:
    """True, если в прошлом ходе (между двумя последними сообщениями user) вызывали инструмент
    коннектора (передача delegate — не действие)."""
    users = [i for i, m in enumerate(messages) if m.role == "user"]
    if len(users) < 2:
        return False
    return any(_connector_message(m) for m in messages[users[-2] + 1 : users[-1]])


def request(messages: list[ChatMessage]) -> str:
    """Просьба хода: вопрос человека, а если это короткий ответ на уточнение помощника
    («сухая или варёная?» → «Варёная») — прошлая реплика человека и этот ответ."""
    asked = question(messages)
    users = [i for i, m in enumerate(messages) if m.role == "user"]
    if not asked or len(users) < 2 or len(asked.split()) > FOLLOW_UP_WORDS:
        return asked
    said = [m.content for m in messages[users[-2] + 1 : users[-1]] if m.role == "assistant" and m.content]
    if not said or not said[-1].rstrip(" \t\n\"'»)").endswith("?"):
        return asked
    return f"{question(messages[: users[-2] + 1])}\n{asked}"


def _connector_message(message: ChatMessage) -> bool:
    """True у вызова инструмента коннектора (не delegate) и у ответа такого инструмента."""
    if message.role == "tool":
        return message.tool_name != DELEGATE_TOOL
    return bool(message.tool_calls) and all(c.name != DELEGATE_TOOL for c in message.tool_calls)


def flatten(messages: list[ChatMessage], keep_tools: bool = False) -> list[ChatMessage]:
    """Диалог без структуры передач: вызовы delegate убраны, их ответы — ответы assistant.

    Подряд идущие ответы assistant (фраза и ответ цели) склеиваются в один через пробел.
    Вызовы инструментов коннекторов и их ответы с keep_tools остаются как есть (участник
    умеет инструменты), без него — убираются.
    """
    result: list[ChatMessage] = []
    for m in messages:
        if _connector_message(m):
            if keep_tools:
                result.append(m)
            continue
        if m.role == "assistant" and not m.content and m.tool_calls:
            continue
        role = "assistant" if m.role == "tool" else m.role
        last = result[-1] if result else None
        if role == "assistant" and last is not None and last.role == "assistant" and not last.tool_calls:
            result[-1] = ChatMessage("assistant", f"{last.content} {m.content}".strip())
        else:
            result.append(ChatMessage(role, m.content))
    return result


def with_task(messages: list[ChatMessage], task: str) -> list[ChatMessage]:
    """Копия сообщений, где к последнему сообщению user дописана задача от диспетчера."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last = messages[index]
            changed = ChatMessage("user", last.content + TASK_PREFIX + task)
            return [*messages[:index], changed, *messages[index + 1 :]]
    return [*messages, ChatMessage("user", TASK_PREFIX.lstrip() + task)]
