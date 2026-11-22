"""Обучение моделей: наборы и цели, запись фраз с колонки, прослушивание и удаление записей."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from smartesp.contracts import (
    NothingHeardError,
    PhraseRecording,
    RecordRefusedError,
    TrainingBusyError,
    TrainingLookupError,
    TrainingPort,
    TrainJob,
    TrainKit,
    TrainTarget,
)

from .schemas import ErrorOut


class TargetIO(BaseModel):
    """Цель (отдельная модель): откликаться на positive, не откликаться на negative."""

    id: str
    title: str
    positive: list[str]
    negative: list[str] = Field(default_factory=list[str])


class PhraseOut(BaseModel):
    """Фраза целей и сколько её записей у каждого человека."""

    phrase: str
    people: dict[str, int]


class StepOut(BaseModel):
    """Шаг обучения; per_target — делается для выбранной цели."""

    id: str
    title: str
    hint: str
    per_target: bool


class KitOut(BaseModel):
    """Набор для обучения."""

    id: str
    title: str
    description: str
    record_hint: str
    targets: list[TargetIO]
    phrases: list[PhraseOut]
    steps: list[StepOut]


class StepIn(BaseModel):
    """Запуск шага: цель (для шагов цели) и прогон (для встраивания; пусто — последний)."""

    target: str = ""
    run: str = ""


class JobOut(BaseModel):
    """Шаг, который идёт или шёл последним; времена — секунды Unix."""

    kit: str
    step: str
    target: str
    status: Literal["running", "done", "failed", "cancelled"]
    started_at: float
    finished_at: float | None
    stage: str
    done: int
    total: int
    error: str
    log: list[str]
    result: dict[str, Any] | None


class RecordIn(BaseModel):
    """Что записать: колонка, фраза из целей набора, чей голос."""

    device_id: str
    phrase: str
    person: str


class RecordingOut(BaseModel):
    """Запись: имя файла, длительность, пик громкости (дБ; тише −30 — запись тихая)."""

    name: str
    seconds: float
    peak_db: float


_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorOut},
    409: {"model": ErrorOut},
    422: {"model": ErrorOut},
}


def _kit_out(kit: TrainKit) -> KitOut:
    return KitOut.model_validate(dataclasses.asdict(kit))


def _job_out(job: TrainJob) -> JobOut:
    return JobOut.model_validate(dataclasses.asdict(job))


def _out(item: PhraseRecording) -> RecordingOut:
    return RecordingOut.model_validate(dataclasses.asdict(item))


@contextmanager
def _http_errors() -> Iterator[None]:
    """Ошибки обучения → HTTP: нет набора/фразы/записи 404, колонка не может 409, неверно 422."""
    try:
        yield
    except TrainingLookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RecordRefusedError, TrainingBusyError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (NothingHeardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def add_training_routes(secured: APIRouter, training: TrainingPort | None) -> None:
    """Маршруты /training; без обучения (None) — пустой список наборов, остальное 404."""

    def port() -> TrainingPort:
        if training is None:
            raise HTTPException(status_code=404, detail="обучение недоступно")
        return training

    @secured.get("/training")
    def get_kits() -> list[KitOut]:
        return [_kit_out(k) for k in training.kits()] if training is not None else []

    @secured.put("/training/{kit}/targets", responses=_ERRORS)
    def put_targets(kit: str, targets: list[TargetIO]) -> KitOut:
        items = [TrainTarget(t.id, t.title, tuple(t.positive), tuple(t.negative)) for t in targets]
        with _http_errors():
            return _kit_out(port().save_targets(kit, items))

    @secured.post("/training/{kit}/record", responses=_ERRORS)
    async def record(kit: str, body: RecordIn) -> RecordingOut:
        with _http_errors():
            return _out(await port().record(kit, body.device_id, body.phrase, body.person))

    @secured.get("/training/{kit}/recordings", responses=_ERRORS)
    def list_recordings(kit: str, phrase: str = Query(), person: str = Query()) -> list[RecordingOut]:
        with _http_errors():
            return [_out(r) for r in port().recordings(kit, phrase, person)]

    @secured.get("/training/{kit}/recordings/{name}", response_class=FileResponse, responses=_ERRORS)
    def get_recording(kit: str, name: str, phrase: str = Query(), person: str = Query()) -> FileResponse:
        with _http_errors():
            return FileResponse(port().recording_file(kit, phrase, person, name), media_type="audio/wav")

    @secured.delete("/training/{kit}/recordings/{name}", status_code=204, responses=_ERRORS)
    def delete_recording(kit: str, name: str, phrase: str = Query(), person: str = Query()) -> None:
        with _http_errors():
            port().delete_recording(kit, phrase, person, name)

    _add_job_routes(secured, port)


def _add_job_routes(secured: APIRouter, port: Callable[[], TrainingPort]) -> None:
    """Шаги обучения: запуск, ход, остановка; итоги прогонов."""

    @secured.post("/training/{kit}/steps/{step}", status_code=202, responses=_ERRORS)
    async def start_step(kit: str, step: str, body: StepIn) -> JobOut:  # async: шаг — задача в цикле ядра
        with _http_errors():
            return _job_out(port().start_step(kit, step, body.target, body.run))

    @secured.get("/training/{kit}/job", responses=_ERRORS)
    def get_job(kit: str) -> JobOut | None:
        job = port().job(kit)
        return _job_out(job) if job is not None else None

    @secured.delete("/training/{kit}/job", status_code=204, responses=_ERRORS)
    async def stop_job(kit: str) -> None:
        await port().stop_job()

    @secured.get("/training/{kit}/runs", responses=_ERRORS)
    def get_runs(kit: str) -> list[dict[str, Any]]:
        with _http_errors():
            return port().runs(kit)
