"""Данные событий хода (turn_started, turn_heard, turn_finished) для ленты событий."""

import time

from smartesp.contracts import Handoff

from .sentences import DEFAULT_STYLE
from .turn import Turn, answer_text, turn_id


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


def delegation_data(handoff: Handoff) -> dict[str, object]:
    """Передача задачи для события: от кого, кому, какая задача и сделана ли по фразе без вызова."""
    return {"from": handoff.source, "to": handoff.target, "task": handoff.task, "auto": handoff.auto}


def started_data(turn: Turn) -> dict[str, object]:
    """Данные turn_started: какой ход и с какой колонки."""
    return {
        "turn_id": turn_id(turn),
        "device_id": turn.utterance.device_id,
        "device_name": turn.device_name,
    }


def heard_data(turn: Turn) -> dict[str, object]:
    """Данные turn_heard: распознанный текст и время распознавания."""
    return {"turn_id": turn_id(turn), "text": turn.text, "stt_ms": _ms(turn.stt_ms)}


def finished_data(turn: Turn) -> dict[str, object]:
    """Данные turn_finished: время, вопрос, пометки, ответ, путь, передачи и инструменты, итог, задержки.

    guard — сработала страховка честности ("retried", "fallback") или None.

    origin — откуда ход (wake, listen, api); у хода через API ещё source и person, у колонки они пусты.
    interruption — "paused": ответ уступил результату отложенной задачи; "resumed": ход продолжает
    прерванный ответ; иначе None.
    """
    return {
        **started_data(turn),
        "at": time.time(),
        "text": turn.text,
        "annotations": [{"source": a.source, "text": a.text} for a in turn.annotations],
        "style": turn.style,
        "answer": answer_text(turn),
        "status": event_status(turn),
        "path": list(turn.path),
        "delegations": [delegation_data(handoff) for handoff in turn.delegations],
        "tools": list(turn.tools),
        "guard": turn.guard or None,
        "interruption": "paused" if turn.paused else "resumed" if turn.resumed else None,
        "stt_ms": _ms(turn.stt_ms),
        "first_text_ms": _ms(turn.first_text_ms),
        "first_audio_ms": _ms(turn.first_audio_ms),
        "origin": turn.utterance.origin,
        "source": turn.source,
        "person": turn.person,
        "person_id": turn.person_id,
        "kind": "turn",
    }


def undelivered_data(turn: Turn, handoff: Handoff) -> dict[str, object]:
    """Данные turn_finished «запоздавший ответ не дождались»: объявление ядра, вслух ничего.

    turn_id — "late<номер хода>", чтобы не путать с ходами и связать с исходным ходом.
    """
    return {
        **started_data(turn),
        "turn_id": f"late{turn.utterance.turn}",
        "at": time.time(),
        "text": "",
        "annotations": [],
        "style": DEFAULT_STYLE,
        "answer": "",
        "status": "undelivered",
        "path": [handoff.target],
        "delegations": [],
        "origin": "core",
        "kind": "announcement",
    }
