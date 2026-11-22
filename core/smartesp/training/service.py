"""Обучение: наборы, цели владельца и запись фраз с колонки (реализация TrainingPort)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from smartesp.contracts import (
    NothingHeardError,
    PhraseRecording,
    PhraseRecords,
    RecordRefusedError,
    TrainingLookupError,
    TrainKit,
    TrainTarget,
)

from .kits import KitSpec, check_targets, clean_phrase, discover, load_targets, save_targets
from .recordings import RecordingStore

_log = logging.getLogger(__name__)
MAX_PERSON = 40

type Recorder = Callable[[str], Awaitable[bytes | None]]


def _clean_person(person: str) -> str:
    name = " ".join(person.split())
    if not name or len(name) > MAX_PERSON:
        raise ValueError(f"имя человека от 1 до {MAX_PERSON} символов")
    return name


class Training:
    """Наборы из trainers/ (repo), данные — <home>/<набор>/: targets.json и recordings/."""

    def __init__(
        self, trainers: Path, home: Path, record: Recorder, can_record: Callable[[str], bool]
    ) -> None:
        """trainers — папка наборов в репозитории; home — ~/SmartEsp/training; record(колонка) —
        фраза с колонки PCM 16 кГц или None (DeviceHub.record); can_record(колонка) — колонка
        подключена, свободна и умеет listen."""
        self._trainers = trainers
        self._home = home
        self._record = record
        self._can_record = can_record

    def _spec(self, kit: str) -> KitSpec:
        for spec in discover(self._trainers):
            if spec.id == kit:
                return spec
        raise TrainingLookupError(f"нет набора для обучения «{kit}»")

    def _targets(self, spec: KitSpec) -> tuple[TrainTarget, ...]:
        return load_targets(self._home / spec.id / "targets.json", spec.default_targets)

    def _store(self, kit: str) -> RecordingStore:
        return RecordingStore(self._home / kit / "recordings")

    def _kit(self, spec: KitSpec) -> TrainKit:
        targets = self._targets(spec)
        phrases = dict.fromkeys(p for t in targets for p in (*t.positive, *t.negative))
        store = self._store(spec.id)
        counted = tuple(PhraseRecords(p, store.counts(p)) for p in phrases)
        return TrainKit(spec.id, spec.title, spec.description, spec.record_hint, targets, counted)

    def kits(self) -> list[TrainKit]:
        """Наборы с целями и счётом записей."""
        return [self._kit(spec) for spec in discover(self._trainers)]

    def save_targets(self, kit: str, targets: list[TrainTarget]) -> TrainKit:
        """Заменяет цели набора (проверка — как у описания набора)."""
        spec = self._spec(kit)
        raw = [
            {"id": t.id, "title": t.title, "positive": list(t.positive), "negative": list(t.negative)}
            for t in targets
        ]
        save_targets(self._home / spec.id / "targets.json", check_targets(raw))
        return self._kit(spec)

    def _known_phrase(self, kit: str, phrase: str) -> str:
        clean = clean_phrase(phrase)
        if not any(clean in (*t.positive, *t.negative) for t in self._targets(self._spec(kit))):
            raise TrainingLookupError(f"фразы «{clean}» нет в целях набора")
        return clean

    async def record(self, kit: str, device_id: str, phrase: str, person: str) -> PhraseRecording:
        """Фраза с колонки → новая запись; см. TrainingPort.record."""
        clean, who = self._known_phrase(kit, phrase), _clean_person(person)
        if not self._can_record(device_id):
            raise RecordRefusedError("колонка не подключена, занята или со старой прошивкой")
        pcm = await self._record(device_id)
        if pcm is None:
            raise NothingHeardError("колонка ничего не услышала — попробуй ещё раз")
        saved = self._store(kit).save(clean, who, pcm)
        _log.info("Обучение %s: записана «%s» (%s, %.1f с)", kit, clean, who, saved.seconds)
        return saved

    def recordings(self, kit: str, phrase: str, person: str) -> list[PhraseRecording]:
        """Записи фразы человека."""
        return self._store(self._spec(kit).id).list(self._known_phrase(kit, phrase), _clean_person(person))

    def recording_file(self, kit: str, phrase: str, person: str, name: str) -> Path:
        """Путь к записи."""
        return self._store(self._spec(kit).id).file(
            self._known_phrase(kit, phrase), _clean_person(person), name
        )

    def delete_recording(self, kit: str, phrase: str, person: str, name: str) -> None:
        """Удаляет запись."""
        self.recording_file(kit, phrase, person, name).unlink()
