"""HTTP API v1: ресурсы, события по WebSocket."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket
from fastapi.responses import JSONResponse

from smartesp.contracts import (
    ChangeResult,
    CorePort,
    EventFeed,
    ExecutorError,
    FilePlayback,
    SoundsPort,
    Subscription,
    TaskBoard,
    TrainingPort,
    UpdatePort,
    VoiceNotDownloadedError,
)

from .access import lan_addresses
from .ask import add_ask_routes
from .auth import require_token, token_matches
from .core_routes import add_core_routes
from .log_buffer import LogBuffer
from .logs import add_logs_route
from .play import add_play_routes
from .redact import declared_secrets, mask_connector_secrets
from .schemas import (
    AccessOut,
    ChangeOut,
    CloudModelOut,
    ConfigOut,
    ConnectorDetailOut,
    DownloadIn,
    ErrorOut,
    ModelOut,
    PreviewIn,
    StatusOut,
    TurnOut,
    VoiceOut,
)
from .sounds import add_sounds_routes
from .tasks import add_tasks_routes
from .training import add_training_routes
from .updates import add_update_routes

DEFAULT_PREVIEW_TEXT = "Привет! Я буду отвечать этим голосом."
WS_UNAUTHORIZED = 4401
_PATCH_CODES = {"invalid": 422, "stopping": 503}
_UNAUTHORIZED: dict[int | str, dict[str, object]] = {401: {"model": ErrorOut}}


def _change_response(result: ChangeResult, codes: dict[str, int]) -> JSONResponse:
    body = ChangeOut(change_id=result.change_id, status=result.status, error=result.error)  # type: ignore[arg-type]
    return JSONResponse(body.model_dump(), status_code=codes.get(result.status, 200))


def create_api(
    core: CorePort,
    feed: EventFeed,
    token: str,
    *,
    port: int,
    files: FilePlayback,
    logs: LogBuffer,
    tasks: TaskBoard | None = None,
    training: TrainingPort | None = None,
    updates: UpdatePort | None = None,
    sounds: SoundsPort | None = None,
) -> APIRouter:
    """Собирает роутер `/api/v1`; все ресурсы требуют токен.

    `port` — порт сервера для адресов входа; `files` — проигрывание файлов на колонках;
    `logs` — журнал для WebSocket `/logs`; `tasks` — реестр «В работе» (None — пусто);
    `training` — обучение моделей (None — наборов нет); `updates` — обновления колонок по воздуху;
    `sounds` — свои звуки сигналов колонок (None — недоступны).
    """
    router = APIRouter(prefix="/api/v1")
    secured = APIRouter(dependencies=[Depends(require_token(token))], responses=_UNAUTHORIZED)
    _add_resource_routes(secured, core)
    _add_cloud_route(secured, core)
    _add_voice_routes(secured, core)
    add_ask_routes(secured, core)
    add_play_routes(secured, files)
    add_tasks_routes(secured, tasks)
    add_training_routes(secured, training)
    add_update_routes(secured, updates)
    add_sounds_routes(secured, sounds)
    add_core_routes(secured, core, port)
    _add_access_route(secured, token, port)
    router.include_router(secured)
    _add_events_route(router, feed, token)
    add_logs_route(router, logs, token)
    return router


def _add_resource_routes(secured: APIRouter, core: CorePort) -> None:
    """Сводка, настройки, коннекторы, модели, ходы, перезапуск."""

    @secured.get("/status")
    async def get_status() -> StatusOut:
        return StatusOut.model_validate(await core.status())

    @secured.get("/config")
    def get_config() -> ConfigOut:
        secrets = declared_secrets(core.connectors())
        return ConfigOut.model_validate(mask_connector_secrets(core.config(), secrets))

    @secured.patch(
        "/config",
        response_model=ChangeOut,
        responses={422: {"model": ChangeOut}, 503: {"model": ChangeOut}},
    )
    async def patch_config(patch: dict[str, object]) -> JSONResponse:
        return _change_response(await core.patch_config(patch), _PATCH_CODES)

    @secured.get("/connectors")
    async def get_connectors() -> list[ConnectorDetailOut]:
        return [ConnectorDetailOut.model_validate(item) for item in core.connectors()]

    @secured.get("/models", responses={502: {"model": ErrorOut}})
    async def get_models() -> list[ModelOut]:
        try:
            items = await core.models()
        except ExecutorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return [ModelOut.model_validate(item) for item in items]

    @secured.get("/turns")
    def get_turns(limit: int = Query(100, ge=1, le=1000)) -> list[TurnOut]:
        return [TurnOut.model_validate(item) for item in core.turns(limit)]

    @secured.post("/restart", status_code=202)
    def restart() -> None:
        core.request_restart()


def _add_cloud_route(secured: APIRouter, core: CorePort) -> None:
    """Модели облачного сервиса для выбора в настройках исполнителя."""

    @secured.get("/cloud/models", responses={502: {"model": ErrorOut}})
    async def get_cloud_models() -> list[CloudModelOut]:
        try:
            items = await core.cloud_models()
        except ExecutorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return [CloudModelOut.model_validate(item) for item in items]


def _add_access_route(secured: APIRouter, token: str, port: int) -> None:
    """Адреса входа из локальной сети."""

    # Намеренно sync `def`: FastAPI гонит её в потоке, а getaddrinfo на macOS может зависнуть на секунды.
    @secured.get("/access")
    def get_access() -> AccessOut:
        return AccessOut(urls=[f"http://{ip}:{port}/?token={token}" for ip in lan_addresses()])


def _add_voice_routes(secured: APIRouter, core: CorePort) -> None:
    """Каталог голосов, скачивание и пробное озвучивание."""

    @secured.get("/voices")
    def get_voices() -> list[VoiceOut]:
        return [VoiceOut.model_validate(item) for item in core.voices()]

    @secured.post(
        "/voices/download",
        status_code=202,
        response_model=ChangeOut,
        responses={422: {"model": ChangeOut}, 503: {"model": ChangeOut}},
    )
    async def download_voice(body: DownloadIn) -> JSONResponse:
        result = await core.download_voice(body.kind, body.voice)
        return _change_response(result, {"stopping": 503, "accepted": 202, "invalid": 422})

    @secured.post(
        "/voices/preview",
        response_class=Response,
        responses={
            200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}},
            404: {"model": ErrorOut},
            409: {"model": ErrorOut},
            500: {"model": ErrorOut},
        },
    )
    async def preview_voice(body: PreviewIn) -> Response:
        text = body.text or DEFAULT_PREVIEW_TEXT
        try:
            wav = await core.preview(body.kind, body.voice, body.style, text)
        except VoiceNotDownloadedError as error:
            raise HTTPException(status_code=409, detail="Голос не скачан") from error
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Голос не найден") from error
        except RuntimeError as error:
            raise HTTPException(status_code=500, detail="Не удалось озвучить образец") from error
        return Response(content=wav, media_type="audio/wav")


def _add_events_route(router: APIRouter, feed: EventFeed, token: str) -> None:
    """WebSocket с событиями; токен — в `?token=`."""

    @router.websocket("/events")
    async def events(websocket: WebSocket) -> None:
        # Сначала accept: так клиент получает код закрытия 4401, а не голый HTTP 403.
        await websocket.accept()
        if not token_matches(websocket.query_params.get("token"), token):
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        async with aclosing(feed.subscribe()) as subscription:
            sender = asyncio.create_task(_send_events(websocket, subscription))
            receiver = asyncio.create_task(_wait_disconnect(websocket))
            try:
                await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (sender, receiver):
                    task.cancel()
                await asyncio.wait({sender, receiver})


async def _send_events(websocket: WebSocket, subscription: Subscription) -> None:
    """Шлёт события клиенту; одно «плохое» событие не рвёт соединение."""
    async for event in subscription:
        payload = {"kind": event.kind, "data": event.data, "at": event.at}
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            continue
        await websocket.send_text(text)


async def _wait_disconnect(websocket: WebSocket) -> None:
    """Читает сокет, пока клиент не отключится (иначе обрыв не заметить)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
