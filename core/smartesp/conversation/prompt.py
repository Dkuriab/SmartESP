"""Сборка сообщений для исполнителя."""

from smartesp.contracts import Annotation, ChatMessage

# заголовок сообщения контекста: без него модель не считает пометки «пометками в сообщении»
# (проба: метка шёпота [style:quiet] 0/12 без заголовка, 11/12 с ним)
CONTEXT_HEAD = "Пометки к следующему сообщению человека:"
# справка (время, колонка): без запрета модель вставляет её в ответы («в этот вечер»,
# «Чем могу помочь, Кухня?»): проба 5/48 → 0/48, README ядра, «Обработчики фразы»
REFERENCE_HEAD = (
    "Справочные данные — только для инструментов и прямых вопросов, к разговору не относятся."
    " Не упоминай их в ответе, если человек о них не спросил:"
)
SPEAKER = "колонка"  # название строки с именем колонки в справке


def _reference(annotations: list[Annotation], device_name: str) -> list[ChatMessage]:
    """Сообщение справки «REFERENCE_HEAD время — …; колонка — ….» или пустой список."""
    items = [f"{a.label or a.source} — {a.text}" for a in annotations if a.reference and a.to_model]
    if device_name:
        items.append(f"{SPEAKER} — {device_name}")
    return [ChatMessage("system", f"{REFERENCE_HEAD} {'; '.join(items)}.")] if items else []


def _notes(annotations: list[Annotation]) -> list[ChatMessage]:
    """Сообщение «CONTEXT_HEAD» с пометками к реплике по строке или пустой список."""
    lines = [f"[{a.label or a.source}] {a.text}" for a in annotations if not a.reference and a.to_model]
    return [ChatMessage("system", "\n".join([CONTEXT_HEAD, *lines]))] if lines else []


def build_messages(
    annotations: list[Annotation], history: list[ChatMessage], text: str, device_name: str
) -> list[ChatMessage]:
    """Собирает диалог для исполнителя: история, справка, пометки к реплике и слова человека.

    Справка (пометки с reference — время — и имя колонки) — одно сообщение system:
    REFERENCE_HEAD и «название — значение» через «; ». Остальные пометки — следующее
    сообщение system: заголовок CONTEXT_HEAD и по строке «[источник] текст». Пустое
    имя колонки — без неё (вопрос не с колонки); пометки с to_model=False (только для
    ленты) не идут никуда; нечего сказать — сообщения нет. Оба
    стоят прямо перед вопросом: начало диалога не меняется от хода к ходу (кэш модели).
    В сообщении user — только сам текст вопроса: так модель не переносит справку в
    параметры инструментов (имя таймера из имени колонки, время еды из времени).
    Системное описание добавляет исполнитель. Возвращает новый список, history не меняется.
    """
    context = [*_reference(annotations, device_name), *_notes(annotations)]
    return [*history, *context, ChatMessage("user", text)]
