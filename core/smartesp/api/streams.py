"""Потоки звука на колонках: очередь (файлы и ссылки), управление, громкость; звук — ссылкой колонке.

Коды: 404 — колонки нет; 409 — не в сети, протокол < 5, на колонке ничего не играет или не понятно,
какая колонка; 422 — источник не годится; 503 — ядро останавливается.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from smartesp.contracts import SpeakerStreams, StreamInfo, StreamItem, StreamRefusal, StreamRefused

from .schemas import ErrorOut

CODES: dict[StreamRefusal, int] = {
    "unknown_device": 404,
    "offline": 409,
    "unsupported": 409,
    "not_playing": 409,
    "no_device": 409,
    "bad_source": 422,
    "unavailable": 503,
}
_ERRORS: dict[int | str, dict[str, object]] = {code: {"model": ErrorOut} for code in (404, 409, 422, 503)}
PCM_TYPE = "audio/L16; rate=16000; channels=1"  # сырой PCM s16le (на деле little-endian, как в протоколе)


class StreamItemIn(BaseModel):
    """Элемент очереди: полный путь к звуковому файлу на Mac или ссылка http(s); название."""

    source: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)


class StreamPlayIn(BaseModel):
    """Новая очередь: колонка (нет — колонка последнего разговора или единственная), элементы, с
    какого номера и секунды начать, громкость музыки 0..1 (нет — прежняя колонки)."""

    device_id: str | None = None
    items: list[StreamItemIn] = Field(min_length=1, max_length=1000)
    index: int = Field(default=0, ge=0)
    start_s: float = Field(default=0.0, ge=0.0)
    volume: float | None = Field(default=None, ge=0.0, le=1.0)


class StreamControlIn(BaseModel):
    """Действие с потоком колонки (нет — единственная с потоком или колонка последнего разговора)."""

    device_id: str | None = None
    action: Literal["pause", "resume", "next", "previous", "stop"]


class StreamVolumeIn(BaseModel):
    """Громкость музыки: volume (0..1) или сдвиг delta (-1..1)."""

    device_id: str | None = None
    volume: float | None = Field(default=None, ge=0.0, le=1.0)
    delta: float = Field(default=0.0, ge=-1.0, le=1.0)


class StreamOut(BaseModel):
    """Поток на колонке (см. contracts.StreamInfo)."""

    device_id: str
    name: str
    available: bool
    state: Literal["idle", "playing", "paused"]
    title: str
    index: int
    count: int
    position_s: float
    live: bool
    volume: float
    error: str


def _out(info: StreamInfo) -> StreamOut:
    return StreamOut.model_validate(info, from_attributes=True)


def _refused(error: StreamRefused) -> HTTPException:
    return HTTPException(status_code=CODES[error.reason], detail=str(error))


def _add_inputs_route(secured: APIRouter, streams: SpeakerStreams | None) -> None:
    """GET /streams/inputs: устройства ввода Mac для «звука Mac» — выбор в настройках коннектора."""

    @secured.get("/streams/inputs")
    async def stream_inputs() -> list[str]:  # pyright: ignore[reportUnusedFunction]
        return await streams.inputs() if streams is not None else []


def add_stream_routes(secured: APIRouter, streams: SpeakerStreams | None) -> None:
    """GET и POST /streams, GET /streams/inputs, POST /streams/control и /streams/volume."""
    _add_inputs_route(secured, streams)

    def need() -> SpeakerStreams:
        if streams is None:
            raise HTTPException(status_code=503, detail="Потоки недоступны")
        return streams

    @secured.get("/streams")
    def get_streams() -> list[StreamOut]:
        return [_out(info) for info in streams.status()] if streams is not None else []

    @secured.post("/streams", responses=_ERRORS)
    async def play_stream(body: StreamPlayIn) -> StreamOut:
        items = [StreamItem(item.source, item.title) for item in body.items]
        try:
            info = await need().play(
                body.device_id, items, index=body.index, start_s=body.start_s, volume=body.volume
            )
        except StreamRefused as error:
            raise _refused(error) from error
        return _out(info)

    @secured.post("/streams/control", responses=_ERRORS)
    async def control_stream(body: StreamControlIn) -> StreamOut:
        try:
            return _out(await need().control(body.device_id, body.action))
        except StreamRefused as error:
            raise _refused(error) from error

    @secured.post("/streams/volume", responses=_ERRORS)
    async def stream_volume(body: StreamVolumeIn) -> StreamOut:
        try:
            return _out(await need().set_volume(body.device_id, volume=body.volume, delta=body.delta))
        except StreamRefused as error:
            raise _refused(error) from error


def add_device_streams(app: FastAPI, streams: SpeakerStreams | None) -> None:
    """GET /device/stream/{токен}: звук потока для колонки (без токена API; ссылка одноразовая).

    Колонка спрашивает по HTTP/1.0 — ответ без chunked, конец потока — закрытие соединения.
    """

    @app.get("/device/stream/{token}", include_in_schema=False)
    async def device_stream(token: str) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        audio = await streams.open(token) if streams is not None else None
        if audio is None:
            raise HTTPException(status_code=502, detail="поток не открылся")
        return StreamingResponse(audio, media_type=PCM_TYPE)
