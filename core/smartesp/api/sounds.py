"""Свои звуки сигналов: GET /sounds, POST и DELETE /sounds/{tone}, WAV для прослушивания, повтор доставки.

Коды: 404 — колонки нет (или звука для прослушивания); 409 — звуки недоступны; 413 — файл больше
MAX_SOUND_FILE; 422 — файл пуст, не разобрать или в нём нет звука; 503 — нет ffmpeg.
Изменения доставки — событие sounds {device_id | null} в /events.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from smartesp.contracts import SoundRef, SoundRefusal, SoundRefusedError, SoundsPort, SoundTone

from .schemas import ErrorOut

MAX_SOUND_FILE = 10 * 1024 * 1024
READ_BYTES = 256 * 1024
TOO_LARGE = "Файл больше 10 МБ — для сигнала нужен короткий звук"
EMPTY = "Пустой звуковой файл"
NO_SOUNDS = "Звуки недоступны"
FILE_HELP = "звук: MP3, WAV, OGG, M4A или FLAC; длиннее 3 с — обрежется"
DEVICE_HELP = "только для этой колонки; нет — для всех (выборы колонок по сигналу сбрасываются)"
CODES: dict[SoundRefusal, int] = {"unknown_device": 404, "undecodable": 422, "unavailable": 503}
_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorOut} for code in (404, 409, 413, 422, 503)
}


class SoundRefOut(BaseModel):
    """Подготовленный звук: SHA-256 (для прослушивания), имя загруженного файла, длина в секундах."""

    sha256: str
    name: str
    duration_s: float


class SoundSetOut(BaseModel):
    """Итог загрузки: звук и обрезан ли он до 3 с."""

    sound: SoundRefOut
    trimmed: bool


class DeviceSoundOut(BaseModel):
    """Сигнал на колонке: source — builtin | all (общий) | device (свой); sound — None у встроенного;
    delivery — ok | pending | sending | failed | unsupported (прошивка без звуков) | offline."""

    tone: Literal["wake", "error", "thinking", "listen", "attention"]
    source: Literal["builtin", "all", "device"]
    sound: SoundRefOut | None
    delivery: Literal["ok", "pending", "sending", "failed", "unsupported", "offline"]
    error: str = ""


class DeviceSoundsOut(BaseModel):
    """Звуки колонки; supported — прошивка умеет звуки (None — колонка ещё не подключалась)."""

    device_id: str
    supported: bool | None
    tones: list[DeviceSoundOut]


class CommonSoundOut(BaseModel):
    """Общий звук сигнала (для всех колонок); None — встроенный."""

    tone: Literal["wake", "error", "thinking", "listen", "attention"]
    sound: SoundRefOut | None


class SoundsOut(BaseModel):
    """Общие звуки и звуки каждой известной колонки."""

    common: list[CommonSoundOut]
    devices: list[DeviceSoundsOut]


def add_sounds_routes(secured: APIRouter, sounds: SoundsPort | None) -> None:
    """Маршруты /sounds; без звуков — 409."""

    def port() -> SoundsPort:
        if sounds is None:
            raise HTTPException(status_code=409, detail=NO_SOUNDS)
        return sounds

    _add_read_routes(secured, port)
    _add_change_routes(secured, port)


def _add_read_routes(secured: APIRouter, port: Callable[[], SoundsPort]) -> None:
    """GET /sounds и WAV для прослушивания."""

    @secured.get("/sounds", responses={409: {"model": ErrorOut}})
    def get_sounds() -> SoundsOut:
        overview = port().overview()
        common = [CommonSoundOut(tone=t, sound=_ref(s)) for t, s in overview.common.items()]
        devices = [DeviceSoundsOut.model_validate(dataclasses.asdict(d)) for d in overview.devices]
        return SoundsOut(common=common, devices=devices)

    @secured.get(
        "/sounds/files/{sha256}",
        response_class=Response,
        responses={200: {"content": {"audio/wav": {}}}, 404: {"model": ErrorOut}},
    )
    def sound_file(sha256: str) -> Response:
        wav = port().wav(sha256)
        if wav is None:
            raise HTTPException(status_code=404, detail="Нет такого звука")
        return Response(wav, media_type="audio/wav")


def _add_change_routes(secured: APIRouter, port: Callable[[], SoundsPort]) -> None:
    """Повтор доставки, загрузка и встроенный звук."""

    # до /sounds/{tone}: иначе «sync» разбирался бы как сигнал
    @secured.post("/sounds/sync", status_code=202, responses={409: {"model": ErrorOut}})
    async def resync() -> None:  # async: доставка — задачи в цикле ядра
        port().resync()

    @secured.post("/sounds/{tone}", responses=_ERRORS)
    async def set_sound(
        tone: SoundTone,
        file: Annotated[UploadFile, File(description=FILE_HELP)],
        device_id: Annotated[str | None, Query(description=DEVICE_HELP)] = None,
    ) -> SoundSetOut:
        if file.size is not None and file.size > MAX_SOUND_FILE:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        if file.size == 0:
            raise HTTPException(status_code=422, detail=EMPTY)
        try:
            result = await port().set_sound(tone, _chunks(file), file.filename or "звук", device_id)
        except SoundRefusedError as error:
            raise HTTPException(status_code=CODES[error.reason], detail=str(error)) from error
        return SoundSetOut.model_validate(dataclasses.asdict(result))

    @secured.delete("/sounds/{tone}", status_code=204, responses=_ERRORS)
    async def reset_sound(
        tone: SoundTone, device_id: Annotated[str | None, Query(description=DEVICE_HELP)] = None
    ) -> None:
        try:
            await port().reset(tone, device_id)
        except SoundRefusedError as error:
            raise HTTPException(status_code=CODES[error.reason], detail=str(error)) from error


def _ref(sound: SoundRef | None) -> SoundRefOut | None:
    return SoundRefOut.model_validate(dataclasses.asdict(sound)) if sound is not None else None


async def _chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """Загрузка кусками, не больше MAX_SOUND_FILE (тело без длины тоже)."""
    total = 0
    while chunk := await upload.read(READ_BYTES):
        total += len(chunk)
        if total > MAX_SOUND_FILE:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        yield chunk
