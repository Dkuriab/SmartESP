"""Сборка сообщений для исполнителя."""

from smartesp.contracts import Annotation, ChatMessage

# заголовок сообщения контекста: без него модель не считает пометки «пометками в сообщении»
# (проба: метка шёпота [style:quiet] 0/12 без заголовка, 11/12 с ним)
CONTEXT_HEAD = "Пометки к следующему сообщению человека:"


def build_messages(
    annotations: list[Annotation], history: list[ChatMessage], text: str, device_name: str
) -> list[ChatMessage]:
    """Собирает диалог для исполнителя: история, сообщение о контексте хода и слова человека.

    Контекст — отдельное сообщение system прямо перед вопросом: заголовок CONTEXT_HEAD,
    пометки обработчиков по строке («[источник] текст») и строка «Колонка: имя» (пустое
    имя — без неё: вопрос не с колонки). Нет ни пометок, ни колонки — сообщения нет. В
    сообщении user — только сам текст вопроса: так модель не переносит пометки в параметры
    инструментов (имя таймера «Тест» из строки колонки, время еды «вечер» из пометки
    времени). Системное описание добавляет исполнитель. Возвращает новый список, history
    не меняется.
    """
    lines = [f"[{a.label or a.source}] {a.text}" for a in annotations]
    if device_name:
        lines.append(f"Колонка: {device_name}")
    context = [ChatMessage("system", "\n".join([CONTEXT_HEAD, *lines]))] if lines else []
    return [*history, *context, ChatMessage("user", text)]
