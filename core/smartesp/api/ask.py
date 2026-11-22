"""Ход через API: вопрос текстом (`/ask`) или голосом (`/ask/voice`) — ответ текстом.

Коды: 200 — ответ (и честное «Не расслышала.»); 413 — звук больше MAX_AUDIO_BYTES;
422 — неверный запрос или звук не разобрать; 503 — ядро не готово, останавливается или
нет ffmpeg. Клиент (бот) ждёт ответа 60 с, ядро укладывает ход в 55 с.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, StringConstraints

from smartesp.contracts import Answer, AskUnavailable, AudioUndecodable, CorePort, Question

from .schemas import ErrorOut

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # голосовое больше — 413
TOO_LARGE = "Голосовое сообщение больше 10 МБ"
EMPTY_AUDIO = "Пустой звуковой файл"
_ERRORS: dict[int | str, dict[str, object]] = {422: {"model": ErrorOut}, 503: {"model": ErrorOut}}
_VOICE_ERRORS: dict[int | str, dict[str, object]] = {**_ERRORS, 413: {"model": ErrorOut}}

PERSON_PATTERN = r"^[^\x00-\x1f\x7f]*$"  # без управляющих символов: имя — одна строка промпта
SOURCE_PATTERN = r"^[a-z0-9_-]{1,32}$"
# аккаунт в канале (id пользователя Telegram): идёт в id гостя "<канал>:<аккаунт>" — без «/» и «\»
ACCOUNT_PATTERN = r"^[^\x00-\x1f\x7f/\\]*$"
Person = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64, pattern=PERSON_PATTERN)]
Source = Annotated[str, StringConstraints(pattern=SOURCE_PATTERN)]
Account = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64, pattern=ACCOUNT_PATTERN)]


class AskIn(BaseModel):
    """Вопрос через API текстом: текст, кто спрашивает ("" — неизвестно), откуда (для ленты) и
    аккаунт в этом канале (id пользователя Telegram; по нему ядро находит человека из «Людей»)."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    person: Person = ""
    source: Source = "api"
    account: Account = ""


class AskOut(BaseModel):
    """Ответ на вопрос через API: текст ответа и номер хода в ленте."""

    answer: str
    turn_id: str


def add_ask_routes(secured: APIRouter, core: CorePort) -> None:
    """POST /ask и POST /ask/voice."""

    @secured.post("/ask", responses=_ERRORS)
    async def ask(body: AskIn) -> AskOut:
        question = Question(text=body.text, person=body.person, source=body.source, account=body.account)
        return await _answer(core.ask(question))

    @secured.post("/ask/voice", responses=_VOICE_ERRORS)
    async def ask_voice(
        audio: Annotated[UploadFile, File(description="голосовое: OGG/Opus или WAV, до 10 МБ")],
        person: Annotated[str, Form(max_length=64, pattern=PERSON_PATTERN)] = "",
        source: Annotated[str, Form(pattern=SOURCE_PATTERN)] = "api",
        account: Annotated[str, Form(max_length=64, pattern=ACCOUNT_PATTERN)] = "",
    ) -> AskOut:
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        if not data:
            raise HTTPException(status_code=422, detail=EMPTY_AUDIO)
        return await _answer(core.ask_voice(data, person.strip(), source, account.strip()))


async def _answer(turn: Awaitable[Answer]) -> AskOut:
    """Ждёт ход и переводит его исход в ответ HTTP."""
    try:
        answer = await turn
    except AudioUndecodable as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AskUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AskOut(answer=answer.text, turn_id=answer.turn_id)
