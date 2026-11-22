"""Обучение: наборы, цели владельца и запись фраз с колонки (реализация TrainingPort)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from smartesp.contracts import (
    NothingHeardError,
    PhraseRecording,
    PhraseRecords,
    RecordRefusedError,
    TrainingBusyError,
    TrainingLookupError,
    TrainJob,
    TrainKit,
    TrainTarget,
)

from .jobs import StepJob
from .kits import KitSpec, check_targets, clean_phrase, discover, load_targets, save_targets
from .recordings import RecordingStore

_log = logging.getLogger(__name__)
MAX_PERSON = 40

type Recorder = Callable[[str], Awaitable[bytes | None]]


def _substitute(arg: str, values: dict[str, str]) -> str:
    """Подставляет {kit}, {repo}, {target}, {run} внутри аргумента."""
    for key, value in values.items():
        arg = arg.replace(key, value)
    return arg


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
        self._jobs: dict[str, StepJob] = {}  # последний шаг каждого набора
        self._running: asyncio.Task[None] | None = None

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
        return TrainKit(spec.id, spec.title, spec.description, spec.record_hint, targets, counted, spec.steps)

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

    # ---- шаги обучения ----

    def _argv(self, spec: KitSpec, step: str, target: str, run: str) -> list[str]:
        """Команда набора + аргументы шага; {kit}, {repo}, {target}, {run} подставляются."""
        if not spec.command or step not in spec.step_args:
            raise TrainingLookupError(f"у набора «{spec.id}» нет шага «{step}»")
        values = {
            "{kit}": str(spec.folder),
            "{repo}": str(self._trainers.parent),
            "{target}": target,
            "{run}": run or "last",
        }
        argv = [_substitute(a, values) for a in (*spec.command, *spec.step_args[step])]
        if argv[0] == "uv":  # ядро запущено через uv run: он сообщает свой путь в UV
            argv[0] = os.environ.get("UV") or shutil.which("uv") or "uv"
        return argv

    def _env(self) -> dict[str, str]:
        """Окружение шага: та же папка данных, без окружения ядра (у набора своё)."""
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        return {**env, "SMARTESP_HOME": str(self._home.parent), "PYTHONUNBUFFERED": "1"}

    def start_step(self, kit: str, step: str, target: str = "", run: str = "") -> TrainJob:
        """Запускает шаг; см. TrainingPort.start_step."""
        if self._running is not None and not self._running.done():
            raise TrainingBusyError("уже идёт шаг обучения — дождитесь его или остановите")
        spec = self._spec(kit)
        info = next((s for s in spec.steps if s.id == step), None)
        if info is None:
            raise TrainingLookupError(f"у набора «{kit}» нет шага «{step}»")
        if info.per_target and not any(t.id == target for t in self._targets(spec)):
            raise TrainingLookupError(f"нет цели «{target}»")
        state = TrainJob(kit, step, target if info.per_target else "", "running", time.time())
        job = StepJob(state, self._argv(spec, step, target, run), self._env())
        self._jobs[kit] = job
        self._running = asyncio.create_task(job.run(), name=f"training {kit}/{step}")
        _log.info("Обучение %s: шаг %s %s", kit, step, target)
        return job.snapshot()

    async def stop_job(self) -> None:
        """Останавливает идущий шаг."""
        for job in self._jobs.values():
            await job.stop()
        if self._running is not None:
            await asyncio.gather(self._running, return_exceptions=True)

    async def aclose(self) -> None:
        """Остановка ядра: идущий шаг останавливается (его процесс не должен пережить ядро)."""
        await self.stop_job()

    def job(self, kit: str) -> TrainJob | None:
        """Идущий или последний шаг набора."""
        job = self._jobs.get(kit)
        return job.snapshot() if job is not None else None

    def runs(self, kit: str) -> list[dict[str, object]]:
        """Итоги прогонов (result.json без кривой roc), новые первыми; битые пропускаются."""
        found: list[dict[str, object]] = []
        for path in sorted((self._home / self._spec(kit).id / "runs").glob("*/result.json"), reverse=True):
            try:
                data = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                entry: dict[str, object] = {
                    str(k): v for k, v in cast(dict[object, object], data).items() if k != "roc"
                }
                found.append({**entry, "run": path.parent.name})
        return found
