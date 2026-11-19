"""Диалог для цели передачи: плоский, с задачей от диспетчера; вопрос человека; закрытие потоков."""

import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from smartesp.contracts import ChatMessage, ReplyPart

TASK_PREFIX = "\n\nЗадача от диспетчера: "  # дописывается к последнему сообщению user у цели
# строки перед вопросом в сообщении user (их собирает conversation.build_messages)
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


def flatten(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Диалог для цели: без вызовов инструментов, ответы инструментов — ответы assistant.

    Подряд идущие ответы assistant (фраза и ответ цели) склеиваются в один через пробел.
    """
    result: list[ChatMessage] = []
    for m in messages:
        if m.role == "assistant" and not m.content and m.tool_calls:
            continue
        role = "assistant" if m.role == "tool" else m.role
        if role == "assistant" and result and result[-1].role == "assistant":
            result[-1] = ChatMessage("assistant", f"{result[-1].content} {m.content}".strip())
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
