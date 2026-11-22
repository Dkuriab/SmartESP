"""Договор: люди дома, образцы их голоса и узнавание того, кто говорит."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .ask import Question
from .audio import Utterance


@dataclass(frozen=True)
class VoiceSample:
    """Образец голоса: отпечаток одной фразы (сам звук не хранится).

    model — id модели отпечатков: отпечатки разных моделей несравнимы.
    """

    id: str
    at: float  # time.time() записи
    device_id: str
    seconds: float
    peak_db: float  # пик громкости, дБ от полной шкалы
    model: str
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class PersonLink:
    """Связь человека с аккаунтом в канале: channel — как source хода ("telegram"), account — id там.

    Аккаунт принадлежит не больше чем одному человеку; у человека связей может быть несколько.
    """

    channel: str
    account: str


@dataclass(frozen=True)
class Person:
    """Человек дома: постоянный id (папка, _meta.person скиллам), имя (промпт, лента, _meta.person_name),
    образцы голоса и связи с аккаунтами в каналах (Telegram и др.)."""

    id: str
    name: str
    created_at: float  # time.time()
    samples: tuple[VoiceSample, ...] = ()
    links: tuple[PersonLink, ...] = ()


@dataclass(frozen=True)
class Recognition:
    """Итог узнавания фразы: кто говорит (пустой person_id — не узнан) и насколько похоже."""

    at: float  # time.time()
    device_id: str
    turn: int
    person_id: str
    name: str
    score: float  # косинусное сходство с лучшим из людей (−1…1)
    ms: float  # сколько заняло узнавание


@dataclass(frozen=True)
class SpeakerModelState:
    """Модель отпечатков: скачана ли, идёт ли скачивание и сколько скачано."""

    model: str
    title: str
    size_mb: int
    ready: bool
    downloading: bool = False
    done_bytes: int = 0
    total_bytes: int | None = None
    error: str = ""


class PeopleLookupError(LookupError):
    """Нет такого человека или образца."""


class SpeakerModelMissingError(Exception):
    """Модель отпечатков не скачана: записать образец или узнать голос нельзя."""


class VoicePrint(Protocol):
    """Сменная часть: звук фразы → голосовой отпечаток (вектор единичной длины)."""

    model: str  # id модели: у образца хранится, отпечатки разных моделей не сравниваются

    def embed(self, pcm: bytes) -> list[float]:
        """Отпечаток фразы (PCM s16le 16 кГц моно). Тяжёлое — вызывать в потоке."""
        ...


class PeoplePort(Protocol):
    """Люди для API: реестр, запись образцов с колонки, узнавания, модель отпечатков."""

    def people(self) -> list[Person]:
        """Все люди по времени добавления."""
        ...

    def add(self, name: str) -> Person:
        """Добавляет человека; неверное или занятое имя — ValueError."""
        ...

    def rename(self, person_id: str, name: str) -> Person:
        """Переименовывает; нет человека — PeopleLookupError, неверное или занятое имя — ValueError."""
        ...

    def delete(self, person_id: str) -> None:
        """Удаляет человека со всеми образцами; нет — PeopleLookupError."""
        ...

    async def record_sample(self, person_id: str, device_id: str) -> VoiceSample:
        """Пишет фразу с колонки (пикает и слушает до паузы) и сохраняет её отпечаток.

        Нет человека — PeopleLookupError; модели нет — SpeakerModelMissingError; колонка не
        может — RecordRefusedError; речи не было или фраза короткая — NothingHeardError.
        """
        ...

    def delete_sample(self, person_id: str, sample_id: str) -> None:
        """Удаляет образец; нет человека или образца — PeopleLookupError."""
        ...

    def add_link(self, person_id: str, channel: str, account: str) -> Person:
        """Связывает человека с аккаунтом канала (уже связан с ним — ничего не меняет).

        Нет человека — PeopleLookupError; неверный канал или аккаунт, аккаунт у другого — ValueError.
        """
        ...

    def remove_link(self, person_id: str, channel: str, account: str) -> Person:
        """Убирает связь; нет человека или такой связи — PeopleLookupError."""
        ...

    def identify(self, question: Question) -> Question:
        """Вопрос через API с человеком: связан (source, account) — его id и имя; не связан —
        id "<source>:<account>" и имя от клиента; без account — как есть."""
        ...

    def name_of(self, person_id: str) -> str:
        """Имя по постоянному id (человек или известный гость канала); неизвестен — сам id."""
        ...

    def recognitions(self) -> list[Recognition]:
        """Последние узнавания, новые первыми (только в памяти)."""
        ...

    def model_state(self) -> SpeakerModelState:
        """Состояние модели отпечатков."""
        ...

    def download_model(self) -> SpeakerModelState:
        """Начинает скачивание модели в фоне (уже есть или качается — ничего не делает)."""
        ...

    async def recognize(self, utterance: Utterance) -> Recognition | None:
        """Кто говорит во фразе; None — судить не по кому или не по чему (нет людей, модели, звука)."""
        ...
