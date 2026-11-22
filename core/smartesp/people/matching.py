"""Сопоставление отпечатка с людьми: средний отпечаток человека, косинус, порог и отрыв.

Замер на синтетических голосах (дизайн, §4.2): при пороге 0,55 и отрыве 0,05 свои узнаются
все, чужой голос принимается за своего в 1 % фраз. Живые голоса менее стабильны, чем
синтетические, — порог первым проверять на колонках («Последние узнавания» показывают сходство).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from smartesp.contracts import Person

THRESHOLD = 0.55  # сходство с лучшим ниже — «не узнан»
MARGIN = 0.05  # лучший должен опережать второго человека хотя бы на столько, иначе «не узнан»


@dataclass(frozen=True)
class Match:
    """Итог сопоставления: узнанный человек (None — не узнан) и сходство с лучшим."""

    person: Person | None
    score: float


def centroid(person: Person, model: str) -> np.ndarray | None:
    """Средний отпечаток образцов модели model (единичной длины); образцов нет — None."""
    vectors = [s.embedding for s in person.samples if s.model == model]
    if not vectors:
        return None
    mean = np.mean(np.asarray(vectors, dtype=np.float64), axis=0)
    norm = float(np.linalg.norm(mean))
    return mean / norm if norm > 0 else None


def has_voice(person: Person, model: str) -> bool:
    """Есть ли у человека образцы модели model (участвует ли он в узнавании)."""
    return any(s.model == model for s in person.samples)


def best_match(
    embedding: Sequence[float],
    people: Sequence[Person],
    model: str,
    threshold: float = THRESHOLD,
    margin: float = MARGIN,
) -> Match:
    """Лучший по косинусу человек, если он не ниже порога и опережает второго на margin."""
    vector = np.asarray(embedding, dtype=np.float64)
    scored: list[tuple[float, Person]] = []
    for person in people:
        center = centroid(person, model)
        if center is not None:
            scored.append((float(vector @ center), person))
    if not scored:
        return Match(None, 0.0)
    scored.sort(key=lambda item: item[0], reverse=True)
    best, person = scored[0]
    second = scored[1][0] if len(scored) > 1 else -1.0
    if best >= threshold and best - second >= margin:
        return Match(person, best)
    return Match(None, best)
