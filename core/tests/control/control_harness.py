"""Общая обвязка тестов пульта: поддельные разделы, журнал вызовов и сборка Core."""

from __future__ import annotations

import asyncio
from typing import Any

from fakes.fake_control import FakeConfigStore, FakeVoices
from fakes.fake_events import RecordingSink
from smartesp.contracts import DeviceInfo, Section
from smartesp.control import Core
from smartesp.events import EventBus

LIVE = ("devices", "executors", "stages", "history")

INITIAL: dict[str, Any] = {
    "version": 3,
    "server": {"port": 8765},
    "stt": {"kind": "mlx_whisper"},
    "arbitration": {"window_ms": 300},
    "devices": {},
    "tts": {"kind": "silero", "voice": "xenia"},
    "executors": [{"id": "main", "model": "qwen"}],
    "stages": {},
    "history": {"turns": 10},
}


class LogSink(RecordingSink):
    """Запоминает события и пишет их вид в общий журнал."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log
        self.failures = 0  # столько ближайших публикаций бросят ошибку

    def publish(self, kind: str, data: dict[str, object]) -> None:
        self._log.append(f"event {kind}")
        super().publish(kind, data)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("подписчик упал")


class FakeSection:
    """Раздел: build ждёт gate и может упасть; swap/release пишут в журнал."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log
        self.current: object = f"{name}:initial"
        self.gate: asyncio.Event | None = None
        self.release_gate: asyncio.Event | None = None
        self.error: Exception | None = None

    async def build(self, config: Any) -> object:
        self.log.append(f"build {self.name}")
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return f"{self.name}:{config[self.name]}"

    def swap(self, part: object) -> object | None:
        self.log.append(f"swap {self.name}")
        old, self.current = self.current, part
        return old

    async def release(self, old: object) -> None:
        self.log.append(f"release {old}")
        if self.release_gate is not None:
            await self.release_gate.wait()  # как ожидание конца звучащего хода

    def section(self) -> Section:
        return Section(build=self.build, swap=self.swap, release=self.release)


class Harness:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.store = FakeConfigStore(INITIAL)
        self.store.on_save = self.log
        self.events = LogSink(self.log)
        self.voices = FakeVoices()
        self.voices.on_open = self.log
        self.bus = EventBus()
        self.sections = {name: FakeSection(name, self.log) for name in LIVE}
        self.now = 100.0
        self.loaded_models: list[str] | Exception = ["qwen"]
        self.loaded_gate: asyncio.Event | None = None
        self.model_list: list[tuple[str, int]] | Exception = [("qwen", 5_000)]
        self.device_list: list[DeviceInfo] = []
        self.core = Core(
            self.store,
            {name: s.section() for name, s in self.sections.items()},
            events=self.events,
            feed=self.bus,
            voices=self.voices,
            models=self._models,
            loaded=self._loaded,
            devices=lambda: self.device_list,
            version="1.2.3",
            clock=lambda: self.now,
        )

    async def _models(self) -> list[tuple[str, int]]:
        if isinstance(self.model_list, Exception):
            raise self.model_list
        return self.model_list

    async def _loaded(self) -> list[str]:
        if self.loaded_gate is not None:
            await self.loaded_gate.wait()
        if isinstance(self.loaded_models, Exception):
            raise self.loaded_models
        return self.loaded_models

    def applied(self) -> list[dict[str, object]]:
        """Данные событий change_applied по порядку."""
        return [data for kind, data in self.events.events if kind == "change_applied"]

    async def settle(self, count: int) -> None:
        """Ждёт, пока придёт count событий change_applied."""
        async with asyncio.timeout(1):
            while len(self.applied()) < count:
                await asyncio.sleep(0)

    async def spin(self, times: int = 20) -> None:
        """Даёт циклу событий прокрутиться."""
        for _ in range(times):
            await asyncio.sleep(0)
