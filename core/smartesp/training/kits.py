"""Наборы для обучения: описание trainers/<id>/smartesp.json и цели владельца (targets.json)."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, cast

from smartesp.contracts import TrainStep, TrainTarget

MAX_TARGETS = 10
MAX_PHRASES = 40  # в одном списке цели
MAX_PHRASE = 40  # символов во фразе
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class KitSpec:
    """Описание набора: id, название, пояснение, подсказка записи и цели по умолчанию."""

    def __init__(self, folder: Path, data: dict[str, Any]) -> None:
        self.folder = folder
        self.id = str(data.get("id") or folder.name)
        self.title = str(data.get("title") or self.id)
        self.description = str(data.get("description") or "")
        self.record_hint = str(data.get("record_hint") or "")
        self.default_targets = check_targets(data.get("targets") or [])
        self.command = [str(a) for a in cast(list[object], data.get("command") or [])]
        self.steps = _steps(data.get("steps"))
        self.step_args = {
            str(s.get("id")): [str(a) for a in s.get("args") or []] for s in _step_dicts(data.get("steps"))
        }


def _step_dicts(raw: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], s) for s in cast(list[object], raw)] if isinstance(raw, list) else []


def _steps(raw: object) -> tuple[TrainStep, ...]:
    """Шаги набора из описания: [{id, title, hint, per_target, args}]."""
    return tuple(
        TrainStep(
            str(s["id"]), str(s.get("title") or s["id"]), str(s.get("hint") or ""), bool(s.get("per_target"))
        )
        for s in _step_dicts(raw)
        if s.get("id")
    )


def discover(trainers: Path) -> list[KitSpec]:
    """Наборы из trainers/*/smartesp.json (по имени папки); неверное описание пропускается."""
    kits: list[KitSpec] = []
    for manifest in sorted(trainers.glob("*/smartesp.json")):
        try:
            kits.append(KitSpec(manifest.parent, json.loads(manifest.read_text("utf-8"))))
        except (OSError, ValueError):
            continue
    return kits


def clean_phrase(value: object) -> str:
    """Фраза без лишних пробелов; пустая, длинная или с управляющими символами — ValueError."""
    if not isinstance(value, str):
        raise ValueError("фраза должна быть строкой")
    phrase = " ".join(value.split())
    if not phrase or len(phrase) > MAX_PHRASE:
        raise ValueError(f"фраза от 1 до {MAX_PHRASE} символов: «{phrase}»")
    if any(unicodedata.category(c).startswith("C") for c in phrase) or "/" in phrase:
        raise ValueError(f"недопустимый символ во фразе «{phrase}»")
    return phrase


def _phrases(value: object, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(cast(list[object], value)) > MAX_PHRASES:
        raise ValueError(f"{what}: список до {MAX_PHRASES} фраз")
    found = [clean_phrase(v) for v in cast(list[object], value)]
    return tuple(dict.fromkeys(found))  # без повторов, порядок владельца


def check_targets(raw: object) -> tuple[TrainTarget, ...]:
    """Цели из JSON-списка [{id, title, positive, negative}]; ошибка — ValueError с понятным текстом."""
    if not isinstance(raw, list) or not 0 < len(cast(list[object], raw)) <= MAX_TARGETS:
        raise ValueError(f"нужна хотя бы одна цель, не больше {MAX_TARGETS}")
    targets: list[TrainTarget] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ValueError("цель — объект {id, title, positive, negative}")
        entry = cast(dict[str, object], item)
        tid = entry.get("id")
        if not isinstance(tid, str) or not _ID.match(tid) or any(t.id == tid for t in targets):
            raise ValueError(f"id цели — латиница, цифры и _, без повторов: {tid!r}")
        positive = _phrases(entry.get("positive"), "«Откликаться на»")
        if not positive:
            raise ValueError(f"у цели {tid} нет ни одной фразы «Откликаться на»")
        negative = tuple(
            p for p in _phrases(entry.get("negative", []), "«Не откликаться на»") if p not in positive
        )
        title = entry.get("title")
        targets.append(
            TrainTarget(
                tid, title.strip() if isinstance(title, str) and title.strip() else tid, positive, negative
            )
        )
    return tuple(targets)


def load_targets(path: Path, defaults: tuple[TrainTarget, ...]) -> tuple[TrainTarget, ...]:
    """Цели владельца из targets.json; нет файла или он испорчен — цели по умолчанию."""
    try:
        return check_targets(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError):
        return defaults


def save_targets(path: Path, targets: tuple[TrainTarget, ...]) -> None:
    """Пишет targets.json атомарно."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {"id": t.id, "title": t.title, "positive": list(t.positive), "negative": list(t.negative)}
        for t in targets
    ]
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temp, path)
