"""Обновления колонок по воздуху: прошивка из приложения, файл для колонки по одноразовой ссылке."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from smartesp.contracts import UpdatePort, UpdateRefusedError

from .schemas import ErrorOut

MAX_UPLOAD = 0x400000 + 1  # прошивка — не больше слота (4 МБ); на байт больше — уже «слишком большая»


def add_update_routes(secured: APIRouter, updates: UpdatePort | None) -> None:
    """POST /devices/{id}/firmware: колонка скачает и поставит прошивку (.bin), затем перезагрузится."""

    @secured.post(
        "/devices/{device_id}/firmware",
        status_code=202,
        responses={409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
    )
    async def install_firmware(
        device_id: str, firmware: Annotated[UploadFile, File(description="образ прошивки ESP32 (.bin)")]
    ) -> None:
        if updates is None:
            raise HTTPException(status_code=409, detail="обновления недоступны")
        data = await firmware.read(MAX_UPLOAD)
        try:
            await updates.install(device_id, "firmware", data)
        except UpdateRefusedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error


def add_device_files(app: FastAPI, updates: UpdatePort | None) -> None:
    """GET /device/files/{токен}: файл обновления для колонки (без токена API; ссылка одноразовая)."""

    @app.get("/device/files/{token}", include_in_schema=False)
    def device_file(token: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        path = updates.file(token) if updates is not None else None
        if path is None:
            raise HTTPException(status_code=404, detail="нет файла")
        return FileResponse(path, media_type="application/octet-stream")
