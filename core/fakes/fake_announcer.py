"""Подделка очереди объявлений: запоминает, что ядро хотело сказать."""

from __future__ import annotations


class FakeAnnouncer:
    def __init__(self) -> None:
        self.said: list[tuple[str, str, str]] = []  # (колонка, текст, кто говорит)

    def say(self, device_id: str, text: str, source: str) -> None:
        self.said.append((device_id, text, source))
