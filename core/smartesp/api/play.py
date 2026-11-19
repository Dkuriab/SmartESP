"""Файл на колонке: POST /devices/{id}/play начинает (202), DELETE останавливает.

Коды POST: 202 — колонка начала получать звук (итог — событие playback_finished); 404 — колонки
нет; 409 — не в сети, протокол < 3 или занята; 413 — файл больше MAX_FILE_BYTES; 422 — файл пуст
или не разобрать; 503 — нет ffmpeg или ядро останавливается. Размер и токен прослойка BodyLimit
проверяет до чтения тела.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from smartesp.contracts import FilePlayback, PlaybackRefusal, PlaybackRefused

from .schemas import ErrorOut, PlayOut, StopOut

MAX_FILE_BYTES = 50 * 1024 * 1024
FILE_HELP = "звуковой файл: MP3, WAV, OGG, M4A или FLAC, до 50 МБ"
READ_BYTES = 256 * 1024  # кусок загрузки при переписывании во временный файл
TOO_LARGE = "Файл больше 50 МБ"
EMPTY_FILE = "Пустой звуковой файл"
CODES: dict[PlaybackRefusal, int] = {
    "unknown_device": 404,
    "offline": 409,
    "unsupported": 409,
    "busy": 409,
    "undecodable": 422,
    "unavailable": 503,
}
_PLAY_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorOut} for code in (404, 409, 413, 422, 503)
}


def add_play_routes(secured: APIRouter, files: FilePlayback) -> None:
    """POST и DELETE /devices/{device_id}/play."""

    @secured.post("/devices/{device_id}/play", status_code=202, responses=_PLAY_ERRORS)
    async def play_file(
        device_id: str,
        audio: Annotated[UploadFile, File(description=FILE_HELP)],
    ) -> PlayOut:
        if audio.size is not None and audio.size > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        if audio.size == 0:
            raise HTTPException(status_code=422, detail=EMPTY_FILE)
        try:
            await files.play_file(device_id, _chunks(audio))
        except PlaybackRefused as error:
            raise HTTPException(status_code=CODES[error.reason], detail=str(error)) from error
        return PlayOut()

    @secured.delete("/devices/{device_id}/play", responses={404: {"model": ErrorOut}})
    async def stop_file(device_id: str) -> StopOut:
        try:
            return StopOut(stopped=await files.stop_file(device_id))
        except PlaybackRefused as error:
            raise HTTPException(status_code=CODES[error.reason], detail=str(error)) from error


async def _chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """Загрузка кусками по READ_BYTES."""
    while chunk := await upload.read(READ_BYTES):
        yield chunk
