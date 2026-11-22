"""Очередь одной колонки: элементы, номер, позиция, состояние и текущий поток на колонке."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from smartesp.contracts import STREAM_RATE, StreamInfo, StreamItem, StreamPhase

from .sources import is_live, title_of

BYTES_PER_S = STREAM_RATE * 2  # PCM s16le моно


@dataclass
class Ticket:
    """Одноразовая ссылка колонки: какой поток, откуда и с какой секунды; до какого времени жива."""

    device_id: str
    stream: int
    source: str
    start_s: float
    until: float


@dataclass
class SpeakerQueue:
    """Очередь колонки. stream — номер потока, отданного колонке (0 — нет); played — байт, о которых
    колонка отчиталась; offset_s — откуда начат поток в элементе; resume_s — позиция паузы."""

    device_id: str
    items: list[StreamItem]
    volume: float
    index: int = 0
    state: StreamPhase = "idle"
    stream: int = 0
    played: int = 0
    offset_s: float = 0.0
    resume_s: float = 0.0
    reported: bool = False  # колонка отчиталась о текущем потоке
    failures: int = 0  # сломанных элементов подряд
    error: str = ""
    stopped: asyncio.Event | None = None  # ждём отчёт stopped (пауза: точная позиция)

    @property
    def item(self) -> StreamItem | None:
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    @property
    def live(self) -> bool:
        item = self.item
        return item is not None and is_live(item.source)

    def position_s(self) -> float:
        """Позиция в элементе: играет — начало потока + доиграно; на паузе — запомненная."""
        if self.state == "paused":
            return self.resume_s
        if self.state == "playing":
            return self.offset_s + self.played / BYTES_PER_S
        return 0.0

    def info(self, name: str, available: bool) -> StreamInfo:
        """Состояние для интерфейса и коннекторов."""
        item = self.item
        title = (item.title or title_of(item.source)) if item is not None else ""
        return StreamInfo(
            self.device_id,
            name,
            available,
            state=self.state,
            title=title if self.state != "idle" else "",
            index=self.index,
            count=len(self.items),
            position_s=round(self.position_s(), 1),
            live=self.live,
            volume=round(self.volume, 2),
            error=self.error,
        )
