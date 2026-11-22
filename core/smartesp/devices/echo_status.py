"""echo_status колонки (прошивка 0.7.0): разбор события калибровки эха."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smartesp.contracts import MAX_ECHO_DELAY_MS

ECHO_STATES = ("current", "running", "done", "failed")


@dataclass(frozen=True)
class EchoStatus:
    """echo_status колонки: состояние, сдвиг сейчас и до калибровки, уверенность, ошибка."""

    state: str
    delay_ms: int
    previous_ms: int
    confidence: float
    error: str


def parse_echo_status(data: dict[str, Any]) -> EchoStatus | None:
    """echo_status из JSON; неверные поля — None."""
    state, error, confidence = data.get("state"), data.get("error", ""), data.get("confidence", 0.0)
    delays = (data.get("delay_ms"), data.get("previous_ms", data.get("delay_ms")))
    if state not in ECHO_STATES or not all(valid_delay(d) for d in delays):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        return None
    error = error if isinstance(error, str) else ""
    return EchoStatus(str(state), int(delays[0]), int(delays[1]), float(confidence), error)  # type: ignore[arg-type]


def valid_delay(value: object) -> bool:
    """Сдвиг — целое 0..MAX_ECHO_DELAY_MS."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_ECHO_DELAY_MS
