"""Калибровка эха колонки (прошивка 0.7.0): запуск и ручной сдвиг образца.

Итог — в status (devices[].echo) и событиях device_echo. Отказ (колонка не подключена, старая
прошивка, занята разговором, калибровка уже идёт, сдвиг вне 0..300) — 409 с текстом.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from smartesp.contracts import MAX_ECHO_DELAY_MS, EchoPort, EchoRefusedError

from .schemas import ErrorOut

_ERRORS: dict[int | str, dict[str, object]] = {409: {"model": ErrorOut}}


class EchoDelayIn(BaseModel):
    """Сдвиг образца эхоподавления вручную, мс."""

    delay_ms: int = Field(ge=0, le=MAX_ECHO_DELAY_MS)


def add_echo_routes(secured: APIRouter, echo: EchoPort | None) -> None:
    """POST /devices/{id}/echo/calibrate и PUT /devices/{id}/echo."""

    def need() -> EchoPort:
        if echo is None:
            raise HTTPException(status_code=409, detail="калибровка эха недоступна")
        return echo

    @secured.post("/devices/{device_id}/echo/calibrate", status_code=202, responses=_ERRORS)
    async def calibrate_echo(device_id: str) -> None:
        try:
            await need().calibrate_echo(device_id)
        except EchoRefusedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @secured.put("/devices/{device_id}/echo", status_code=202, responses=_ERRORS)
    async def set_echo_delay(device_id: str, body: EchoDelayIn) -> None:
        try:
            await need().set_echo_delay(device_id, body.delay_ms)
        except EchoRefusedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
