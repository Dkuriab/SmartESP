"""Состояние одного хода разговора и его итог для журнала."""

import time
from dataclasses import dataclass, field

from smartesp.contracts import Annotation, Utterance


@dataclass
class Turn:
    """Состояние одного хода и замеры задержек (мс от прихода реплики в оркестратор)."""

    utterance: Utterance
    device_name: str
    received_at: float
    text: str = ""
    annotations: list[Annotation] = field(default_factory=list[Annotation])
    answer: list[str] = field(default_factory=list[str])
    stt_ms: float | None = None
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    completed: bool = False  # ответ отдан целиком, ход ещё актуален
    failed: bool = False  # ход сорвался из-за ошибки (исполнитель, TTS, STT…)
    meaningless: bool = False  # распознан бессмысленный текст — ответ пустой
    play_started: bool = False  # хабу уже отдан поток (он сам закончит ответ reply_end)

    def elapsed_ms(self) -> float:
        """Сколько миллисекунд прошло с прихода реплики."""
        return (time.monotonic() - self.received_at) * 1000


def format_ms(value: float | None) -> str:
    """Задержка для журнала: целые миллисекунды или «—», если до этого этапа не дошли."""
    return "—" if value is None else str(round(value))


def answer_text(turn: Turn) -> str:
    """Полный текст ответа исполнителя (то, что успели получить)."""
    return "".join(turn.answer).strip()


def status(turn: Turn) -> str:
    """Итог хода для журнала."""
    if turn.failed:
        return "ошибка"
    if turn.meaningless:
        return "бессмысленный вопрос, пустой ответ"
    return "готов" if turn.completed else "прерван"
