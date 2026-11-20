"""Сообщения протокола колонок: разбор входящих и кодирование исходящих."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

MAX_TURN = 0xFFFFFFFF  # ход — uint32
MAX_BYTES = 0xFFFFFFFF  # счётчик доигранного в played — uint32
LOWEST_LEVEL = -1000.0  # громкость для NaN/бесконечности/переполнения: слово участвует, но проигрывает


@dataclass(frozen=True)
class Hello:
    """Приветствие колонки. Прошивка v1 не шлёт device_id: тогда None и protocol=1."""

    device_id: str | None
    fw: str
    protocol: int


@dataclass(frozen=True)
class Wake:
    """Слово пробуждения. level — громкость в dBFS (None у прошивки v1)."""

    turn: int
    level: float | None


@dataclass(frozen=True)
class UtteranceEnd:
    """Конец реплики. reason: vad | timeout | server | no_speech."""

    turn: int
    reason: str


@dataclass(frozen=True)
class BargeIn:
    """Пользователь перебил ответ."""

    turn: int


@dataclass(frozen=True)
class PlaybackDone:
    """Колонка доиграла ответ."""

    turn: int


@dataclass(frozen=True)
class Busy:
    """Колонка не приняла announce/listen хода turn: она не в покое (протокол 3)."""

    turn: int


@dataclass(frozen=True)
class Played:
    """Сколько звука ответа хода turn колонка уже доиграла (прошивка 0.4.0, расширение протокола 3).

    bytes — байт PCM ответа (16 кГц, 16 бит, моно), отданных динамику с начала ответа.
    Приходит раз в ~0,5 с, пока звучит ответ, и последним перед playback_done.
    """

    turn: int
    bytes: int


DeviceMessage = Hello | Wake | UtteranceEnd | BargeIn | PlaybackDone | Busy | Played


def _turn(data: dict[str, Any]) -> int | None:
    """Достаёт корректный ход (uint32, не bool) или None."""
    turn = data.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or not 0 <= turn <= MAX_TURN:
        return None
    return turn


def _level(data: dict[str, Any]) -> tuple[bool, float | None]:
    """Возвращает (корректно ли поле level, значение). Отсутствие — корректно, None.

    Число, которое не годится для сравнения (NaN, бесконечность, не влезает во float),
    становится LOWEST_LEVEL: слово не теряется, но уступает любой настоящей громкости.
    """
    if "level" not in data or data["level"] is None:
        return True, None
    level = data["level"]
    if isinstance(level, bool) or not isinstance(level, int | float):
        return False, None
    try:
        value = float(level)
    except OverflowError:  # огромное целое не влезает в float
        return True, LOWEST_LEVEL
    if not math.isfinite(value):  # NaN и бесконечности ломают сравнение в арбитраже
        return True, LOWEST_LEVEL
    return True, value


def _parse_hello(data: dict[str, Any]) -> Hello | None:
    fw = data.get("fw")
    if not isinstance(fw, str):
        return None
    device_id = data.get("device_id")
    if device_id is not None and not isinstance(device_id, str):
        return None
    protocol = data.get("protocol", 1)
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        return None
    return Hello(device_id=device_id, fw=fw, protocol=protocol)


def _parse_wake(data: dict[str, Any]) -> Wake | None:
    turn = _turn(data)
    ok, level = _level(data)
    if turn is None or not ok:
        return None
    return Wake(turn=turn, level=level)


def _parse_utterance_end(data: dict[str, Any]) -> UtteranceEnd | None:
    turn = _turn(data)
    reason = data.get("reason")
    if turn is None or not isinstance(reason, str):
        return None
    return UtteranceEnd(turn=turn, reason=reason)


def _parse_barge_in(data: dict[str, Any]) -> BargeIn | None:
    turn = _turn(data)
    return None if turn is None else BargeIn(turn)


def _parse_playback_done(data: dict[str, Any]) -> PlaybackDone | None:
    turn = _turn(data)
    return None if turn is None else PlaybackDone(turn)


def _parse_busy(data: dict[str, Any]) -> Busy | None:
    turn = _turn(data)
    return None if turn is None else Busy(turn)


def _parse_played(data: dict[str, Any]) -> Played | None:
    turn = _turn(data)
    count = data.get("bytes")
    if turn is None or isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_BYTES:
        return None
    return Played(turn=turn, bytes=count)


_PARSERS = {
    "hello": _parse_hello,
    "wake": _parse_wake,
    "utterance_end": _parse_utterance_end,
    "barge_in": _parse_barge_in,
    "playback_done": _parse_playback_done,
    "busy": _parse_busy,
    "played": _parse_played,
}


def parse_message(text: str) -> DeviceMessage | None:
    """Разбирает текстовый кадр колонки. Мусор и неизвестный type дают None, не исключение."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):  # мусор и слишком глубокая вложенность
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("type")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    parser = _PARSERS.get(kind) if isinstance(kind, str) else None
    return parser(data) if parser else None  # pyright: ignore[reportUnknownArgumentType]


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def reply_start(turn: int) -> str:
    """Кадр «ответ начинается» для хода turn."""
    return _encode({"type": "reply_start", "turn": turn})


def reply_end(turn: int) -> str:
    """Кадр «ответ закончен» для хода turn."""
    return _encode({"type": "reply_end", "turn": turn})


def announce(turn: int) -> str:
    """Кадр «сейчас будет объявление хода ядра turn»: колонка ждёт reply_start."""
    return _encode({"type": "announce", "turn": turn})


def listen(turn: int) -> str:
    """Кадр «слушай вопрос хода ядра turn»: звук «слушаю» и запись, без wake."""
    return _encode({"type": "listen", "turn": turn})


def cancel_turn(turn: int) -> str:
    """Кадр «отмени ход turn»."""
    return _encode({"type": "cancel_turn", "turn": turn})


def tone(name: str) -> str:
    """Кадр «сыграй короткий сигнал name»."""
    return _encode({"type": "tone", "name": name})


def stop_playback() -> str:
    """Кадр «немедленно остановить воспроизведение»."""
    return _encode({"type": "stop_playback"})
