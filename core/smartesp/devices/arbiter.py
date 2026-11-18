"""Арбитр слов пробуждения: из нескольких колонок побеждает самая громкая."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Decision:
    """Решение арбитра: принять или отменить ход колонки."""

    kind: Literal["accept", "cancel"]
    device_id: str
    turn: int


class Arbiter:
    """Чистая логика без часов и сети: время передаётся снаружи (секунды, monotonic)."""

    def __init__(self, window_s: float, late_s: float) -> None:
        """window_s — длина окна сбора кандидатов; late_s — «поздний» период после решения."""
        self._window_s = window_s
        self._late_s = late_s
        self._window_start: float | None = None
        self._candidates: dict[str, tuple[int, float]] = {}
        self._decided_at: float | None = None
        self._winner: str | None = None
        self._active: dict[str, int] = {}  # принятые и ещё не закончившиеся ходы

    def on_wake(self, device_id: str, turn: int, level: float | None, now: float) -> list[Decision]:
        """Регистрирует слово пробуждения; возвращает решения, готовые прямо сейчас."""
        if level is None:  # прошивка v1: принимаем сразу, в арбитраже не участвует
            return [Decision("accept", device_id, turn)]
        if self._window_start is not None:
            self._candidates[device_id] = (turn, level)
            return []
        if self._is_late(device_id, now):
            return [Decision("cancel", device_id, turn)]
        self._window_start = now
        self._candidates = {device_id: (turn, level)}
        return []

    def poll(self, now: float) -> list[Decision]:
        """Закрывает окно, если оно истекло; возвращает решения (accept, затем cancel)."""
        if self._window_start is None or now - self._window_start < self._window_s:
            return []
        winner = max(self._candidates, key=lambda d: self._candidates[d][1])
        decisions = [Decision("accept", winner, self._candidates[winner][0])]
        decisions += [Decision("cancel", d, t) for d, (t, _) in self._candidates.items() if d != winner]
        for device_id, turn in self._active.items():
            if device_id != winner:
                decisions.append(Decision("cancel", device_id, turn))
        self._active = {winner: self._candidates[winner][0]}
        self._winner = winner
        self._decided_at = now
        self._window_start = None
        self._candidates = {}
        return decisions

    def on_turn_finished(self, device_id: str, turn: int) -> None:
        """Ход закончился или отменён; неизвестный ход игнорируется."""
        if self._active.get(device_id) == turn:
            del self._active[device_id]

    def _is_late(self, device_id: str, now: float) -> bool:
        """Слово чужой колонки сразу после решения — запоздавшее."""
        if self._decided_at is None or device_id == self._winner:
            return False
        return now - self._decided_at < self._late_s
