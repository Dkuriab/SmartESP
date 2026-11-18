"""Подделки для пульта: хранилище настроек и менеджер голосов."""

from __future__ import annotations

import asyncio
import copy
from typing import Any


class FakeConfigStore:
    """Настройки — словарь разделов; разделы-словари сливаются на один уровень вглубь.

    Неизвестный раздел в правке — ValueError. saved — всё, что записано через save.
    """

    def __init__(self, initial: dict[str, Any]) -> None:
        self._defaults = copy.deepcopy(initial)
        self.current: dict[str, Any] = copy.deepcopy(initial)
        self.saved: list[dict[str, Any]] = []
        self.on_save: list[str] | None = None  # общий журнал вызовов, если задан

    def effective(self) -> dict[str, Any]:
        return copy.deepcopy(self.current)

    def overridden(self) -> list[str]:
        return [name for name in self.current if self.current[name] != self._defaults[name]]

    def merge(self, patch: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(self.current)
        for name, value in patch.items():
            if name not in merged:
                raise ValueError(f"неизвестный раздел {name}")
            if value is None:
                merged[name] = copy.deepcopy(self._defaults[name])
            elif isinstance(value, dict) and isinstance(merged[name], dict):
                merged[name] = {**merged[name], **copy.deepcopy(value)}
            else:
                merged[name] = copy.deepcopy(value)
        return merged

    def save(self, config: dict[str, Any]) -> None:
        if self.on_save is not None:
            self.on_save.append("save")
        self.saved.append(config)
        self.current = config

    def section(self, config: dict[str, Any], name: str) -> object:
        return config[name]


class FakeVoices:
    """Менеджер голосов: open отвечает open_result, download ждёт gate (если задан)."""

    def __init__(self) -> None:
        self.open_result = True
        self.opened: list[tuple[str, str, bool]] = []
        self.downloaded: list[tuple[str, str]] = []
        self.download_gate: asyncio.Event | None = None
        self.download_error: Exception | None = None
        self.voice_state: dict[str, object] = {
            "kind": "silero",
            "voice": "xenia",
            "state": "ready",
            "error": None,
        }
        self.voice_catalog: list[dict[str, object]] = []
        self.on_open: list[str] | None = None  # общий журнал вызовов, если задан

    def catalog(self) -> list[dict[str, object]]:
        return self.voice_catalog

    def state(self) -> dict[str, object]:
        return self.voice_state

    async def open(self, kind: str, voice: str, *, retry: bool) -> bool:
        if self.on_open is not None:
            self.on_open.append(f"open {kind}/{voice}")
        self.opened.append((kind, voice, retry))
        return self.open_result

    async def download(self, kind: str, voice: str) -> None:
        if self.download_gate is not None:
            await self.download_gate.wait()
        self.downloaded.append((kind, voice))
        if self.download_error is not None:
            raise self.download_error

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        return f"{kind}/{voice}/{style}/{text}".encode()
