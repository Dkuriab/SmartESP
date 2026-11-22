"""Договор: свои звуки сигналов колонки — назначения владельца и доставка на колонки."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from .device import DeviceInfo, UpdateProgress

# Сигналы колонки (Tone в прошивке): слово услышано, ошибка, «думаю», колонка сама слушает, «внимание».
SoundTone = Literal["wake", "error", "thinking", "listen", "attention"]
SOUND_TONES: tuple[SoundTone, ...] = ("wake", "error", "thinking", "listen", "attention")
SOUNDS_CAP = "sounds"  # возможность колонки в hello: понимает update со звуком (прошивка 0.6.0)

# Откуда звук сигнала на колонке: встроенный, общий для всех колонок, свой у этой колонки.
SoundSource = Literal["builtin", "all", "device"]
# Доставка: на колонке нужный; ждёт очереди; качается; не вышло; прошивка без звуков; не в сети.
SoundDelivery = Literal["ok", "pending", "sending", "failed", "unsupported", "offline"]
# Почему звук не принят: колонки нет; файл не разобрать или в нём тишина; нет ffmpeg.
SoundRefusal = Literal["unknown_device", "undecodable", "unavailable"]


@dataclass(frozen=True)
class SoundRef:
    """Подготовленный звук: SHA-256 файла для колонки (PCM 16 кГц моно s16le), имя загрузки, длина."""

    sha256: str
    name: str
    duration_s: float


@dataclass(frozen=True)
class SoundSet:
    """Итог загрузки: звук и обрезан ли он до предела длины."""

    sound: SoundRef
    trimmed: bool


@dataclass(frozen=True)
class DeviceSound:
    """Сигнал на колонке: откуда звук, сам звук (None — встроенный), доставка и её ошибка."""

    tone: SoundTone
    source: SoundSource
    sound: SoundRef | None
    delivery: SoundDelivery
    error: str = ""


@dataclass(frozen=True)
class DeviceSounds:
    """Звуки одной колонки; supported — прошивка понимает звуки (None — ещё не подключалась)."""

    device_id: str
    supported: bool | None
    tones: list[DeviceSound]


@dataclass(frozen=True)
class SoundsOverview:
    """Общие звуки (для всех колонок; None — встроенный) и звуки каждой известной колонки."""

    common: dict[SoundTone, SoundRef | None]
    devices: list[DeviceSounds]


class SoundRefusedError(Exception):
    """Звук не принят: reason — причина (для кода ответа), текст — для человека."""

    def __init__(self, reason: SoundRefusal, message: str) -> None:
        super().__init__(message)
        self.reason: SoundRefusal = reason


class SoundTargets(Protocol):
    """Что звукам нужно от колонок; реализует DeviceHub."""

    def devices(self) -> list[DeviceInfo]:
        """Подключённые и известные по настройкам колонки."""
        ...

    def device_sounds(self, device_id: str) -> Mapping[str, str] | None:
        """SHA-256 своих звуков колонки по сигналу из её hello; None — не подключена или без звуков."""
        ...

    def expect_sound(self, device_id: str, tone: str) -> asyncio.Future[UpdateProgress]:
        """Ожидание итога (done | failed) следующего update звука tone на колонке."""
        ...


class SoundsPort(Protocol):
    """Звуки для API; реализует модуль sounds. Изменения — событие sounds {device_id | None}."""

    def overview(self) -> SoundsOverview:
        """Назначения и доставка по колонкам."""
        ...

    async def set_sound(
        self, tone: SoundTone, source: AsyncIterator[bytes], name: str, device_id: str | None
    ) -> SoundSet:
        """Готовит файл (MP3, WAV, OGG, M4A, FLAC) и назначает его сигналу tone: всем колонкам
        (device_id None — и сбрасывает их отдельные выборы) или одной. Доставка — в фоне.
        Не принят — SoundRefusedError."""
        ...

    async def reset(self, tone: SoundTone, device_id: str | None) -> None:
        """Встроенный звук сигнала tone: всем колонкам (None) или одной. Колонки нет — SoundRefusedError."""
        ...

    def wav(self, sha256: str) -> bytes | None:
        """Звук как WAV для прослушивания; нет такого — None."""
        ...

    def resync(self) -> None:
        """Повторить доставку на все подключённые колонки (после неудачи)."""
        ...
