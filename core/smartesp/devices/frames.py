"""Кадры ядра → колонка (протокол WebSocket): ответ, ходы ядра, сигналы, обновления, громкость, потоки.

Разбор сообщений колонки — в messages.py.
"""

from __future__ import annotations

import json
from typing import Any

from smartesp.contracts import StreamCommand


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


def update(payload: dict[str, Any]) -> str:
    """Кадр «обнови себя» (протокол 4): what, path, size, sha256 и для модели cutoff, window, arena, word;
    для звука — tone (size 0 без path и sha256 — вернуть встроенный)."""
    return _encode({"type": "update", **payload})


def volume(percent: int) -> str:
    """Кадр «громкость» (0–100 % → 0..1)."""
    return _encode({"type": "volume", "value": round(max(0, min(100, percent)) / 100, 2)})


def stream(command: StreamCommand) -> str:
    """Кадр потока (протокол 5): stream_start {stream, path, rate, volume, live}, stream_stop {stream},
    stream_volume {value}."""
    if command.kind == "start":
        fields = {
            "stream": command.stream,
            "path": command.path,
            "rate": command.rate,
            "volume": command.volume,
            "live": command.live,
        }
        return _encode({"type": "stream_start", **fields})
    if command.kind == "stop":
        return _encode({"type": "stream_stop", "stream": command.stream})
    return _encode({"type": "stream_volume", "value": command.volume})
