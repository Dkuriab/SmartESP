"""Данные событий хода (turn_started, turn_heard, turn_finished) для ленты событий."""

from .turn import Turn, answer_text


def _ms(value: float | None) -> int | None:
    """Задержка для события: целые миллисекунды или None, если до этапа не дошли."""
    return None if value is None else round(value)


def event_status(turn: Turn) -> str:
    """Итог хода для события: ok, error, meaningless или interrupted."""
    if turn.failed:
        return "error"
    if turn.meaningless:
        return "meaningless"
    return "ok" if turn.completed else "interrupted"


def started_data(turn: Turn) -> dict[str, object]:
    """Данные turn_started: какой ход и с какой колонки."""
    return {
        "turn_id": turn.utterance.turn,
        "device_id": turn.utterance.device_id,
        "device_name": turn.device_name,
    }


def heard_data(turn: Turn) -> dict[str, object]:
    """Данные turn_heard: распознанный текст и время распознавания."""
    return {"turn_id": turn.utterance.turn, "text": turn.text, "stt_ms": _ms(turn.stt_ms)}


def finished_data(turn: Turn) -> dict[str, object]:
    """Данные turn_finished: вопрос, пометки, ответ, итог и задержки хода."""
    return {
        **started_data(turn),
        "text": turn.text,
        "annotations": [{"source": a.source, "text": a.text} for a in turn.annotations],
        "style": turn.style,
        "answer": answer_text(turn),
        "status": event_status(turn),
        "stt_ms": _ms(turn.stt_ms),
        "first_text_ms": _ms(turn.first_text_ms),
        "first_audio_ms": _ms(turn.first_audio_ms),
    }
