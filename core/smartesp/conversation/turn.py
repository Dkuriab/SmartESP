"""Состояние одного хода разговора и его итог для журнала."""

import itertools
import logging
import time
from dataclasses import dataclass, field

from smartesp.contracts import (
    Analyzer,
    Annotation,
    Executor,
    Handoff,
    SpeechToText,
    TextToSpeech,
    ToolCall,
    Utterance,
)

from .sentences import DEFAULT_STYLE, strip_style_tag

_log = logging.getLogger(__name__)

_CLOSERS = " \t\n\"'»“”)!.…"  # кавычки, скобки и «!», «.» после «?» («Правда?!», «Что?..»)
API_ORIGIN = "api"  # origin реплики хода через API (вопрос текстом или голосовым сообщением)


@dataclass(frozen=True)
class Parts:
    """Снимок сменных частей на начало хода: ход доделывается ими, даже если части подменили."""

    stt: SpeechToText
    analyze: Analyzer
    executor: Executor
    tts: TextToSpeech


@dataclass(frozen=True)
class ToolExchange:
    """Законченный вызов инструмента в ходе: кто вызвал, вызов модели и ответ инструмента."""

    executor: str
    call: ToolCall
    result: str


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
    style: str = DEFAULT_STYLE  # стиль озвучки, выбранный моделью
    path: list[str] = field(default_factory=list[str])  # id исполнителей хода по порядку
    delegations: list[Handoff] = field(default_factory=list[Handoff])  # передачи задачи в ходе
    breaks: list[int] = field(
        default_factory=list[int]
    )  # где в answer начинается ответ цели или фраза об ошибке
    deferred: bool = False  # поток ответа цели взяла фоновая задача запоздавшего ответа
    last_sentence: str = ""  # последнее озвученное предложение (после clean_for_speech)
    # законченные вызовы инструментов: {executor, connector, tool, ok}
    tools: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    exchanges: list[ToolExchange] = field(default_factory=list[ToolExchange])  # те же вызовы для истории
    source: str = ""  # ход через API: откуда вопрос ("telegram"); у колонки — пусто
    person: str = ""  # ход через API: кто спрашивает; неизвестно — пусто
    guard: str = ""  # страховка честности: "retried" (повторный прогон) или "fallback" (честная фраза)

    def elapsed_ms(self) -> float:
        """Сколько миллисекунд прошло с прихода реплики."""
        return (time.monotonic() - self.received_at) * 1000


def turn_id(turn: Turn) -> int | str:
    """Номер хода для событий и ответа: у колонки — её номер хода, у хода через API — "api<номер>"."""
    number = turn.utterance.turn
    return f"{API_ORIGIN}{number}" if turn.utterance.origin == API_ORIGIN else number


def history_question(turn: Turn) -> str:
    """Вопрос хода для истории: у хода через API — с пометкой источника («[Telegram · Аня] текст»)."""
    if not turn.source:
        return turn.text
    who = f"{turn.device_name} · {turn.person}" if turn.person else turn.device_name
    return f"[{who}] {turn.text}"


def format_ms(value: float | None) -> str:
    """Задержка для журнала: целые миллисекунды или «—», если до этого этапа не дошли."""
    return "—" if value is None else str(round(value))


def answer_text(turn: Turn) -> str:
    """Полный текст ответа (то, что успели получить): ответы исполнителей хода через пробел.

    Метка стиля снимается с начала ответа каждого исполнителя.
    """
    bounds = [0, *turn.breaks, len(turn.answer)]
    texts = (strip_style_tag("".join(turn.answer[a:b]))[1].strip() for a, b in itertools.pairwise(bounds))
    return " ".join(text for text in texts if text)


def asks_question(turn: Turn) -> bool:
    """True, если ход доведён до конца без ошибки и последнее озвученное предложение — вопрос."""
    return turn.completed and not turn.failed and turn.last_sentence.rstrip(_CLOSERS).endswith("?")


def status(turn: Turn) -> str:
    """Итог хода для журнала."""
    if turn.failed:
        return "ошибка"
    if turn.meaningless:
        return "бессмысленный вопрос, пустой ответ"
    return "готов" if turn.completed else "прерван"


def log_turn(turn: Turn) -> None:
    """Пишет в журнал итог хода: вопрос, пометки, задержки и ответ."""
    _log.info(
        "Колонка %s: ход %s; вопрос %r; пометки %s; путь %s; стиль %s; "
        "stt_ms=%s first_text_ms=%s first_audio_ms=%s; ответ %r",
        turn.device_name,
        status(turn),
        turn.text,
        [f"[{a.label or a.source}] {a.text}" for a in turn.annotations],
        " → ".join(turn.path) or "—",
        turn.style,
        format_ms(turn.stt_ms),
        format_ms(turn.first_text_ms),
        format_ms(turn.first_audio_ms),
        answer_text(turn),
    )
