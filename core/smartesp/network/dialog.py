"""Диалог для цели передачи: плоский, с задачей от диспетчера."""

from smartesp.contracts import ChatMessage

TASK_PREFIX = "\n\nЗадача от диспетчера: "  # дописывается к последнему сообщению user у цели


def flatten(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Диалог для цели: без вызовов инструментов, ответы инструментов — обычные ответы assistant."""
    return [
        ChatMessage("assistant", m.content) if m.role == "tool" else ChatMessage(m.role, m.content)
        for m in messages
        if m.role != "assistant" or m.content or not m.tool_calls
    ]


def with_task(messages: list[ChatMessage], task: str) -> list[ChatMessage]:
    """Копия сообщений, где к последнему сообщению user дописана задача от диспетчера."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last = messages[index]
            changed = ChatMessage("user", last.content + TASK_PREFIX + task)
            return [*messages[:index], changed, *messages[index + 1 :]]
    return [*messages, ChatMessage("user", TASK_PREFIX.lstrip() + task)]
