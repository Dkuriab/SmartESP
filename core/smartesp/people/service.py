"""Люди (реализация PeoplePort): реестр, запись образцов с колонки, узнавание и его журнал."""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import logging
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np

from smartesp.contracts import (
    SAMPLE_RATE,
    NothingHeardError,
    PeopleLookupError,
    Person,
    Question,
    Recognition,
    RecordRefusedError,
    SpeakerModelMissingError,
    SpeakerModelState,
    Utterance,
    VoicePrint,
    VoiceSample,
)

from .fetching import Fetch, ModelFetcher
from .links import clean_link, guest_id, owner
from .matching import best_match, has_voice
from .store import PeopleStore, clean_name, new_id

MIN_SECONDS = 1.0  # фраза короче — отпечаток ненадёжен: не судим и не записываем
MAX_SAMPLES = 20  # образцов у человека; новый сверх предела вытесняет самый старый
RECENT = 20  # узнаваний в журнале (только в памяти)
_BYTES_PER_SECOND = SAMPLE_RATE * 2
WARM_UP_PCM = bytes(_BYTES_PER_SECOND)  # 1 с тишины: загрузка модели и первый прогон

type Recorder = Callable[[str], Awaitable[bytes | None]]

_log = logging.getLogger(__name__)


def _peak_db(pcm: bytes) -> float:
    """Пик громкости PCM s16le в дБ от полной шкалы (тишина — −120)."""
    samples = np.frombuffer(pcm[: len(pcm) & ~1], dtype="<i2")
    peak = int(np.max(np.abs(samples.astype(np.int32)))) if len(samples) else 0
    return round(20 * math.log10(peak / 32768), 1) if peak else -120.0


class People:
    """Люди из <home>/people; модель отпечатков — <home>/models/speaker (скачивается по просьбе)."""

    def __init__(
        self,
        root: Path,
        model_file: Path,
        voiceprint: VoicePrint,
        fetch: Fetch,
        record: Recorder,
        can_record: Callable[[str], bool],
    ) -> None:
        """root — папка людей; model_file — файл модели (есть — готова); voiceprint — отпечатки;
        fetch(progress) — скачать модель; record(колонка) — фраза с колонки PCM или None
        (DeviceHub.record); can_record(колонка) — колонка подключена, свободна и умеет слушать."""
        self._store = PeopleStore(root)
        self._voiceprint = voiceprint
        self._fetcher = ModelFetcher(model_file, fetch, on_ready=self._warm_soon)
        self._record = record
        self._can_record = can_record
        self._people = {p.id: p for p in self._store.load()}
        self._recent: collections.deque[Recognition] = collections.deque(maxlen=RECENT)
        self._warming: asyncio.Task[None] | None = None
        self._guests: dict[str, str] = {}  # id гостя канала → имя, которое прислал клиент (в памяти)

    # --- реестр ---

    def people(self) -> list[Person]:
        """Все люди по времени добавления."""
        return sorted(self._people.values(), key=lambda p: p.created_at)

    def _get(self, person_id: str) -> Person:
        person = self._people.get(person_id)
        if person is None:
            raise PeopleLookupError("нет такого человека")
        return person

    def _put(self, person: Person) -> Person:
        self._store.save(person)
        self._people[person.id] = person
        return person

    def _taken(self, except_id: str = "") -> list[str]:
        return [p.name for p in self._people.values() if p.id != except_id]

    def add(self, name: str) -> Person:
        """Новый человек без образцов."""
        person = Person(new_id(), clean_name(name, self._taken()), time.time())
        _log.info("Люди: добавлен «%s»", person.name)
        return self._put(person)

    def rename(self, person_id: str, name: str) -> Person:
        """Новое имя (образцы остаются)."""
        person = self._get(person_id)
        return self._put(dataclasses.replace(person, name=clean_name(name, self._taken(person_id))))

    def delete(self, person_id: str) -> None:
        """Удаляет человека и его папку."""
        person = self._get(person_id)
        self._store.remove(person_id)
        del self._people[person_id]
        _log.info("Люди: удалён «%s»", person.name)

    def delete_sample(self, person_id: str, sample_id: str) -> None:
        """Удаляет образец."""
        person = self._get(person_id)
        samples = tuple(s for s in person.samples if s.id != sample_id)
        if len(samples) == len(person.samples):
            raise PeopleLookupError("нет такого образца")
        self._put(dataclasses.replace(person, samples=samples))

    # --- связи с аккаунтами каналов ---

    def add_link(self, person_id: str, channel: str, account: str) -> Person:
        """Связь человека с аккаунтом; аккаунт у другого человека — ValueError."""
        person, link = self._get(person_id), clean_link(channel, account)
        other = owner(self._people.values(), link)
        if other is not None and other.id != person_id:
            raise ValueError(f"{link.channel} {link.account} уже связан с «{other.name}»")
        if link in person.links:
            return person
        _log.info("Люди: «%s» связан с %s", person.name, link.channel)
        return self._put(dataclasses.replace(person, links=(*person.links, link)))

    def remove_link(self, person_id: str, channel: str, account: str) -> Person:
        """Убирает связь человека с аккаунтом."""
        person = self._get(person_id)
        links = tuple(k for k in person.links if (k.channel, k.account) != (channel, account))
        if len(links) == len(person.links):
            raise PeopleLookupError("нет такой связи")
        return self._put(dataclasses.replace(person, links=links))

    def identify(self, question: Question) -> Question:
        """Человек вопроса через API по связи (source, account); см. PeoplePort.identify."""
        if not question.account:
            return question
        try:
            link = clean_link(question.source, question.account)
        except ValueError:
            return question  # аккаунт не годится в id: вопрос — без человека, как без account
        found = owner(self._people.values(), link)
        if found is not None:
            return dataclasses.replace(question, person_id=found.id, person=found.name)
        guest = guest_id(link)
        if question.person:
            self._guests[guest] = question.person  # имя гостя — для «В работе» и ленты
        return dataclasses.replace(question, person_id=guest)

    def name_of(self, person_id: str) -> str:
        """Имя по постоянному id; неизвестен — сам id."""
        person = self._people.get(person_id)
        return person.name if person is not None else self._guests.get(person_id, person_id)

    # --- образцы и узнавание ---

    async def record_sample(self, person_id: str, device_id: str) -> VoiceSample:
        """Фраза с колонки → отпечаток в образцы человека; см. PeoplePort.record_sample."""
        self._get(person_id)
        if not self._fetcher.ready():
            raise SpeakerModelMissingError("модель узнавания голоса не скачана")
        if not self._can_record(device_id):
            raise RecordRefusedError("колонка не подключена, занята или со старой прошивкой")
        pcm = await self._record(device_id)
        if pcm is None:
            raise NothingHeardError("колонка ничего не услышала — попробуй ещё раз")
        seconds = len(pcm) / _BYTES_PER_SECOND
        if seconds < MIN_SECONDS:
            raise NothingHeardError("фраза короче секунды — скажи что-нибудь подлиннее")
        embedding = await asyncio.to_thread(self._voiceprint.embed, pcm)
        model, peak = self._voiceprint.model, _peak_db(pcm)
        sample = VoiceSample(
            new_id(), time.time(), device_id, round(seconds, 2), peak, model, tuple(embedding)
        )
        person = self._get(person_id)  # пока колонка слушала, человека могли изменить или удалить
        self._put(dataclasses.replace(person, samples=(*person.samples, sample)[-MAX_SAMPLES:]))
        _log.info("Люди: образец голоса «%s» (%.1f с, %s)", person.name, seconds, device_id)
        return sample

    def _candidates(self) -> list[Person]:
        return [p for p in self._people.values() if has_voice(p, self._voiceprint.model)]

    async def recognize(self, utterance: Utterance) -> Recognition | None:
        """Кто говорит; None — нет людей с образцами, модели или фраза короче MIN_SECONDS."""
        candidates = self._candidates()
        if not candidates or not self._fetcher.ready():
            return None
        if len(utterance.pcm) < MIN_SECONDS * _BYTES_PER_SECOND:
            return None
        started = time.monotonic()
        embedding = await asyncio.to_thread(self._voiceprint.embed, utterance.pcm)
        match = best_match(embedding, candidates, self._voiceprint.model)
        ms = (time.monotonic() - started) * 1000
        found = match.person
        result = Recognition(
            time.time(),
            utterance.device_id,
            utterance.turn,
            found.id if found else "",
            found.name if found else "",
            round(match.score, 3),
            round(ms, 1),
        )
        self._recent.appendleft(result)
        _log.info("Голос: %s (сходство %.2f, %.0f мс)", result.name or "не узнан", match.score, ms)
        return result

    def recognitions(self) -> list[Recognition]:
        """Последние узнавания, новые первыми."""
        return list(self._recent)

    # --- модель ---

    def model_state(self) -> SpeakerModelState:
        """Состояние модели отпечатков (id — у модели отпечатков: по нему образцы текущие)."""
        return dataclasses.replace(self._fetcher.state(), model=self._voiceprint.model)

    def download_model(self) -> SpeakerModelState:
        """Скачивание модели в фоне."""
        self._fetcher.start()
        return self.model_state()

    async def warm_up(self) -> None:
        """Прогрев: модель есть — загрузка и первый прогон на тишине (иначе ничего)."""
        if self._fetcher.ready():
            await asyncio.to_thread(self._voiceprint.embed, WARM_UP_PCM)

    def _warm_soon(self) -> None:
        """Модель только что скачана: прогреть в фоне, чтобы первый ход не ждал загрузки."""
        self._warming = asyncio.create_task(self.warm_up(), name="speaker-model-warm-up")

    async def aclose(self) -> None:
        """Перестаёт ждать скачивание и прогрев."""
        await self._fetcher.aclose()
        if self._warming is not None and not self._warming.done():
            self._warming.cancel()
            await asyncio.gather(self._warming, return_exceptions=True)
