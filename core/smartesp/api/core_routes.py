"""Ядро как программа: сведения, честная остановка и выгрузка моделей из памяти Ollama.

GET /core — версия, время работы, состояние, порт и папка данных; POST /core/stop — остановка
с выходом (код 0: приложение не перезапускает ядро); POST /models/unload — выгрузить модель,
которая сейчас в памяти Ollama (имя — в теле: в именах моделей бывает «/»).
Перезапуск — POST /restart (в routes.py).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from smartesp.contracts import CorePort, ExecutorError, ModelNotLoadedError

from .schemas import CoreInfoOut, ErrorOut, UnloadIn

NOT_LOADED = "Модель не загружена"


def add_core_routes(secured: APIRouter, core: CorePort, port: int) -> None:
    """GET /core, POST /core/stop, POST /models/unload; port — порт сервера из настроек."""

    @secured.get("/core")
    def get_core() -> CoreInfoOut:  # pyright: ignore[reportUnusedFunction]
        return CoreInfoOut.model_validate({**core.info(), "port": port})

    @secured.post("/core/stop", status_code=202)
    def stop_core() -> None:  # pyright: ignore[reportUnusedFunction]
        core.request_stop()

    @secured.post(
        "/models/unload", status_code=204, responses={404: {"model": ErrorOut}, 502: {"model": ErrorOut}}
    )
    async def unload_model(body: UnloadIn) -> None:  # pyright: ignore[reportUnusedFunction]
        try:
            await core.unload_model(body.name)
        except ModelNotLoadedError as error:
            raise HTTPException(status_code=404, detail=NOT_LOADED) from error
        except ExecutorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
