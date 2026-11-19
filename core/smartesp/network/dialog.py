"""Диалог для цели передачи: плоский, с задачей от диспетчера."""

from smartesp.contracts import ChatMessage

TASK_PREFIX = "\n\nЗадача от диспетчера: "  # дописывается к последнему сообщению user у цели


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
