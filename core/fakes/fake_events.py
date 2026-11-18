"""Подделка приёмника событий: запоминает всё опубликованное."""

from __future__ import annotations


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def publish(self, kind: str, data: dict[str, object]) -> None:
        self.events.append((kind, data))
