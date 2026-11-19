"""Сборка сообщений для исполнителя."""

from smartesp.contracts import Annotation, ChatMessage


def build_messages(
    annotations: list[Annotation], history: list[ChatMessage], text: str, device_name: str
) -> list[ChatMessage]:
    """Собирает диалог для исполнителя: история + новое сообщение пользователя.

    Сообщение пользователя: пометки обработчиков по строке («[источник] текст»),
    строка «Колонка: имя» (пустое имя — без неё: вопрос не с колонки), пустая строка
    и сам текст вопроса. Системное описание добавляет исполнитель. Возвращает
    новый список, history не меняется.
    """
    lines = [f"[{a.label or a.source}] {a.text}" for a in annotations]
    if device_name:
        lines.append(f"Колонка: {device_name}")
    content = "\n".join(lines) + "\n\n" + text if lines else text
    return [*history, ChatMessage("user", content)]
