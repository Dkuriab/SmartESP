"""Схемы состояния колонки в сводке: обновление по воздуху и калибровка эха."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class UpdateOut(BaseModel):
    """Обновление колонки по воздуху: what — firmware | model; state — sent (команда ушла) | progress |
    done (записано, колонка перезагружается) | failed; error — busy, download, size, hash, write, storage."""

    what: str
    state: str
    done: int
    total: int
    error: str
    at: float  # секунды Unix последнего изменения


class EchoOut(BaseModel):
    """Сдвиг образца эхоподавления колонки (прошивка 0.7.0): state — current (сдвиг сейчас) | sent
    (калибровка попрошена) | running | done | failed; delay_ms — сдвиг сейчас, previous_ms — до
    калибровки; confidence — уверенность 0..1; error — busy | quiet | weak | ""."""

    state: Literal["current", "sent", "running", "done", "failed"]
    delay_ms: int
    previous_ms: int
    confidence: float
    error: str
    at: float  # секунды Unix последнего изменения
