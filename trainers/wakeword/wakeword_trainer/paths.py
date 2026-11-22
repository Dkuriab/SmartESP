"""Где лежат данные набора: ~/SmartEsp/training/wakeword (как у ядра) и общий кэш скачанного."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parents[1]  # trainers/wakeword
REPO_DIR = KIT_DIR.parents[1]
KIT_ID = "wakeword"


def data_home() -> Path:
    """Папка данных ядра: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


@dataclass(frozen=True)
class Paths:
    """Папки набора внутри <данные>/training."""

    training: Path  # <данные>/training

    @property
    def kit(self) -> Path:
        return self.training / KIT_ID

    @property
    def recordings(self) -> Path:
        """Записи с колонок: <фраза>/<человек>/NNNN.wav (пишет ядро)."""
        return self.kit / "recordings"

    @property
    def synth(self) -> Path:
        """Синтетика: <фраза>/<голос>-<вариант>.wav."""
        return self.kit / "synth"

    @property
    def work(self) -> Path:
        """Признаки и промежуточное по целям (можно удалить — пересчитается)."""
        return self.kit / "work"

    @property
    def runs(self) -> Path:
        """Итоги обучений: <время>-<цель>/ (модель, манифест, result.json)."""
        return self.kit / "runs"

    @property
    def cache(self) -> Path:
        """Скачанное один раз (отрицательные примеры, фоны) — общее для наборов."""
        return self.training / "cache"


def default_paths() -> Paths:
    return Paths(data_home() / "training")


@dataclass(frozen=True)
class Target:
    """Цель: отдельная модель — откликаться на positive, не откликаться на negative."""

    id: str
    title: str
    positive: tuple[str, ...]
    negative: tuple[str, ...]


def _targets(raw: list[dict[str, object]]) -> list[Target]:
    def phrases(value: object) -> tuple[str, ...]:
        return tuple(str(p) for p in value) if isinstance(value, list) else ()

    return [
        Target(
            str(t["id"]),
            str(t.get("title") or t["id"]),
            phrases(t.get("positive")),
            phrases(t.get("negative")),
        )
        for t in raw
    ]


def load_targets(paths: Paths) -> list[Target]:
    """Цели владельца (targets.json от вкладки «Обучение»), иначе — из smartesp.json набора."""
    owner = paths.kit / "targets.json"
    if owner.is_file():
        return _targets(json.loads(owner.read_text("utf-8")))
    manifest = json.loads((KIT_DIR / "smartesp.json").read_text("utf-8"))
    return _targets(manifest["targets"])


def find_target(paths: Paths, target_id: str) -> Target:
    """Цель по id; нет — ValueError со списком известных."""
    targets = load_targets(paths)
    for target in targets:
        if target.id == target_id:
            return target
    raise ValueError(f"нет цели {target_id!r}; есть: {', '.join(t.id for t in targets)}")


def folder_name(text: str) -> str:
    """Имя папки фразы — как у ядра (smartesp/training/recordings.py)."""
    import re

    name = re.sub(r"[^\w\- ,!?]+", "", text.strip()).strip().lstrip(".")
    return name[:60] or "_"
