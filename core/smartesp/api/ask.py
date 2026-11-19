"""Ход через API: вопрос текстом (`/ask`) или голосом (`/ask/voice`) — ответ текстом.

Коды: 200 — ответ (и честное «Не расслышала.»); 413 — звук больше MAX_AUDIO_BYTES;
422 — неверный запрос или звук не разобрать; 503 — ядро не готово, останавливается или
нет ffmpeg. Клиент (бот) ждёт ответа 60 с, ядро укладывает ход в 55 с.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from smartesp.contracts import Answer, AskUnavailable, AudioUndecodable, CorePort, Question

from .schemas import AskIn, AskOut, ErrorOut

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # голосовое больше — 413
TOO_LARGE = "Голосовое сообщение больше 10 МБ"
EMPTY_AUDIO = "Пустой звуковой файл"
_ERRORS: dict[int | str, dict[str, object]] = {422: {"model": ErrorOut}, 503: {"model": ErrorOut}}
_VOICE_ERRORS: dict[int | str, dict[str, object]] = {**_ERRORS, 413: {"model": ErrorOut}}


def add_ask_routes(secured: APIRouter, core: CorePort) -> None:
    """POST /ask и POST /ask/voice."""

    @secured.post("/ask", responses=_ERRORS)
    async def ask(body: AskIn) -> AskOut:
        question = Question(text=body.text, person=body.person, source=body.source)
        return await _answer(core.ask(question))

    @secured.post("/ask/voice", responses=_VOICE_ERRORS)
    async def ask_voice(
        audio: Annotated[UploadFile, File(description="голосовое: OGG/Opus или WAV, до 10 МБ")],
        person: Annotated[str, Form(max_length=64)] = "",
        source: Annotated[str, Form(pattern=r"^[a-z0-9_-]{1,32}$")] = "api",
    ) -> AskOut:
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        if not data:
            raise HTTPException(status_code=422, detail=EMPTY_AUDIO)
        return await _answer(core.ask_voice(data, person.strip(), source))


async def _answer(turn: Awaitable[Answer]) -> AskOut:
    """Ждёт ход и переводит его исход в ответ HTTP."""
    try:
        answer = await turn
    except AudioUndecodable as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AskUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AskOut(answer=answer.text, turn_id=answer.turn_id)
