"""Свои звуки сигналов: загрузка владельца → подготовка → библиотека → доставка на колонки."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from pathlib import Path

from smartesp.contracts import (
    SOUND_TONES,
    AskUnavailable,
    AudioUndecodable,
    DeviceSound,
    DeviceSounds,
    EventSink,
    SoundRefusedError,
    SoundSet,
    SoundsOverview,
    SoundTargets,
    SoundTone,
)

from .delivery import RESULT_TIMEOUT_S, Install, SoundDeliveries
from .library import SoundLibrary
from .prepare import prepare_sound, to_wav

type Decode = Callable[[Path], AsyncGenerator[bytes]]  # файл → PCM s16le 16 кГц моно кусками

MAX_DECODE_BYTES = 30 * 32000  # читаем не больше 30 с: тишина в начале и звук, дальше всё равно обрезка
UNKNOWN = "Колонка не найдена"
SILENT = "В файле нет звука"


class Sounds:
    """Реализует SoundsPort. folder — папка звуков в папке данных; decode — разбор файла (ffmpeg);
    targets — колонки (хаб); install — Updates.install; events — приёмник событий sounds."""

    def __init__(
        self,
        folder: Path,
        decode: Decode,
        targets: SoundTargets,
        install: Install,
        *,
        events: EventSink | None = None,
        timeout_s: float = RESULT_TIMEOUT_S,
    ) -> None:
        self._folder = folder
        self._decode = decode
        self._targets = targets
        self._library = SoundLibrary(folder)
        self._deliveries = SoundDeliveries(self._library, targets, install, events, timeout_s)

    def device_connected(self, device_id: str) -> None:
        """Колонка подключилась (слушатель хаба): досылаем ей отличия."""
        self._deliveries.connected(device_id)

    def overview(self) -> SoundsOverview:
        """Общие звуки и звуки каждой известной колонки с доставкой."""
        devices = [
            DeviceSounds(
                info.device_id,
                self._deliveries.supported(info.device_id),
                self._tones(info.device_id, info.connected),
            )
            for info in self._targets.devices()
        ]
        return SoundsOverview(self._library.common(), devices)

    async def set_sound(
        self, tone: SoundTone, source: AsyncIterator[bytes], name: str, device_id: str | None
    ) -> SoundSet:
        """Готовит файл и назначает его сигналу (всем или одной колонке); см. SoundsPort."""
        self._check_device(device_id)
        prepared = await asyncio.to_thread(prepare_sound, await self._read(source))
        if prepared is None:
            raise SoundRefusedError("undecodable", SILENT)
        sound = self._library.add(prepared.pcm, name)
        self._library.assign(tone, sound, device_id)
        self._deliveries.changed(tone)
        return SoundSet(sound, prepared.trimmed)

    async def reset(self, tone: SoundTone, device_id: str | None) -> None:
        """Встроенный звук сигнала всем колонкам или одной."""
        self._check_device(device_id)
        self._library.assign(tone, None, device_id)
        self._deliveries.changed(tone)

    def wav(self, sha256: str) -> bytes | None:
        """Звук как WAV; нет — None."""
        pcm = self._library.pcm(sha256)
        return to_wav(pcm) if pcm is not None else None

    def resync(self) -> None:
        """Повторить доставку на все подключённые колонки, забыв неудачи."""
        self._deliveries.start_all(retry=True)

    async def aclose(self) -> None:
        """Снимает идущие доставки."""
        await self._deliveries.aclose()

    def _tones(self, device_id: str, connected: bool) -> list[DeviceSound]:
        tones: list[DeviceSound] = []
        for tone in SOUND_TONES:
            source, sound = self._library.choice(device_id, tone)
            delivery, error = self._deliveries.state(device_id, tone, connected)
            tones.append(DeviceSound(tone, source, sound, delivery, error))
        return tones

    def _check_device(self, device_id: str | None) -> None:
        if device_id is not None and all(d.device_id != device_id for d in self._targets.devices()):
            raise SoundRefusedError("unknown_device", UNKNOWN)

    async def _read(self, source: AsyncIterator[bytes]) -> bytes:
        """Загрузка → временный файл → PCM (не больше MAX_DECODE_BYTES)."""
        self._folder.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="upload-", dir=self._folder)
        path = Path(name)
        try:
            with os.fdopen(handle, "wb") as file:
                async for chunk in source:
                    await asyncio.to_thread(file.write, chunk)
            return await self._decoded(path)
        finally:
            path.unlink(missing_ok=True)

    async def _decoded(self, path: Path) -> bytes:
        pcm = bytearray()
        try:
            chunks = self._decode(path)
            async with contextlib.aclosing(chunks):
                async for chunk in chunks:
                    pcm += chunk
                    if len(pcm) >= MAX_DECODE_BYTES:
                        break
        except AudioUndecodable as error:
            raise SoundRefusedError("undecodable", str(error)) from error
        except AskUnavailable as error:
            raise SoundRefusedError("unavailable", str(error)) from error
        return bytes(pcm)
