"""Люди: реестр, запись образцов голоса с колонки, последние узнавания, модель отпечатков."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from smartesp.contracts import (
    NothingHeardError,
    PeopleLookupError,
    PeoplePort,
    Person,
    RecordRefusedError,
    SpeakerModelMissingError,
    VoiceSample,
)

from .schemas import ErrorOut


class PersonIn(BaseModel):
    """Имя человека: идёт в справку модели, в ленту и в _meta.person_name скиллов."""

    name: str = Field(max_length=64)


class LinkIO(BaseModel):
    """Связь с аккаунтом канала: channel — как source хода ("telegram"), account — id в канале."""

    channel: str = Field(max_length=32)
    account: str = Field(max_length=64)


class SampleIn(BaseModel):
    """С какой колонки записать образец."""

    device_id: str


class SampleOut(BaseModel):
    """Образец голоса (без отпечатка): когда, с какой колонки, длительность и пик громкости, дБ."""

    id: str
    at: float
    device_id: str
    seconds: float
    peak_db: float


class PersonOut(BaseModel):
    """Человек: постоянный id (скиллам — _meta.person), имя, образцы текущей модели, сколько устаревших
    (другой модели, в узнавании не участвуют) и связи с аккаунтами каналов."""

    id: str
    name: str
    created_at: float
    samples: list[SampleOut]
    stale_samples: int
    links: list[LinkIO]


class RecognitionOut(BaseModel):
    """Узнавание фразы: пустой person_id — голос не узнан; score — сходство с лучшим."""

    at: float
    device_id: str
    turn: int
    person_id: str
    name: str
    score: float
    ms: float


class SpeakerModelOut(BaseModel):
    """Модель отпечатков голоса: скачана ли, идёт ли скачивание, ошибка последнего."""

    model: str
    title: str
    size_mb: int
    ready: bool
    downloading: bool
    done_bytes: int
    total_bytes: int | None
    error: str


_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorOut},
    409: {"model": ErrorOut},
    422: {"model": ErrorOut},
}


def _sample(sample: VoiceSample) -> SampleOut:
    return SampleOut(
        id=sample.id, at=sample.at, device_id=sample.device_id, seconds=sample.seconds, peak_db=sample.peak_db
    )


def _person(person: Person, model: str) -> PersonOut:
    current = [_sample(s) for s in person.samples if s.model == model]
    stale = len(person.samples) - len(current)
    links = [LinkIO(channel=k.channel, account=k.account) for k in person.links]
    return PersonOut(
        id=person.id,
        name=person.name,
        created_at=person.created_at,
        samples=current,
        stale_samples=stale,
        links=links,
    )


@contextmanager
def _http_errors() -> Iterator[None]:
    """Нет человека/образца — 404; модели нет или колонка не может — 409; неверно, тишина — 422."""
    try:
        yield
    except PeopleLookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SpeakerModelMissingError, RecordRefusedError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (NothingHeardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def add_people_routes(secured: APIRouter, people: PeoplePort | None) -> None:
    """Маршруты /people; без модуля людей (None) — пустой список, остальное 404."""

    def port() -> PeoplePort:
        if people is None:
            raise HTTPException(status_code=404, detail="люди недоступны")
        return people

    def out(person: Person) -> PersonOut:
        return _person(person, port().model_state().model)

    @secured.get("/people")
    def list_people() -> list[PersonOut]:
        return [out(p) for p in people.people()] if people is not None else []

    @secured.post("/people", responses=_ERRORS)
    def add_person(body: PersonIn) -> PersonOut:
        with _http_errors():
            return out(port().add(body.name))

    @secured.patch("/people/{person_id}", responses=_ERRORS)
    def rename_person(person_id: str, body: PersonIn) -> PersonOut:
        with _http_errors():
            return out(port().rename(person_id, body.name))

    @secured.delete("/people/{person_id}", status_code=204, responses=_ERRORS)
    def delete_person(person_id: str) -> None:
        with _http_errors():
            port().delete(person_id)

    @secured.post("/people/{person_id}/samples", responses=_ERRORS)
    async def record_sample(person_id: str, body: SampleIn) -> SampleOut:
        with _http_errors():
            return _sample(await port().record_sample(person_id, body.device_id))

    @secured.delete("/people/{person_id}/samples/{sample_id}", status_code=204, responses=_ERRORS)
    def delete_sample(person_id: str, sample_id: str) -> None:
        with _http_errors():
            port().delete_sample(person_id, sample_id)

    _add_link_routes(secured, port)
    _add_status_routes(secured, port)


def _add_link_routes(secured: APIRouter, port: Callable[[], PeoplePort]) -> None:
    """Связи человека с аккаунтами каналов: добавить и убрать (ответ — человек после правки)."""

    def out(person: Person) -> PersonOut:
        return _person(person, port().model_state().model)

    @secured.post("/people/{person_id}/links", responses=_ERRORS)
    def add_link(person_id: str, body: LinkIO) -> PersonOut:
        with _http_errors():
            return out(port().add_link(person_id, body.channel, body.account))

    @secured.delete("/people/{person_id}/links/{channel}/{account}", responses=_ERRORS)
    def remove_link(person_id: str, channel: str, account: str) -> PersonOut:
        with _http_errors():
            return out(port().remove_link(person_id, channel, account))


def _add_status_routes(secured: APIRouter, port: Callable[[], PeoplePort]) -> None:
    """Последние узнавания и модель отпечатков."""

    @secured.get("/people/recognitions", responses=_ERRORS)
    def recognitions() -> list[RecognitionOut]:
        return [RecognitionOut.model_validate(r, from_attributes=True) for r in port().recognitions()]

    @secured.get("/people/model", responses=_ERRORS)
    def model_state() -> SpeakerModelOut:
        return SpeakerModelOut.model_validate(port().model_state(), from_attributes=True)

    @secured.post("/people/model", status_code=202, responses=_ERRORS)
    async def download_model() -> SpeakerModelOut:  # async: скачивание — задача в цикле ядра
        return SpeakerModelOut.model_validate(port().download_model(), from_attributes=True)
