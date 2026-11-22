"""Реестр людей на диске: <root>/<id>/person.json, запись атомарная, права 0600.

Звук образцов не хранится — только отпечатки (приватность, дизайн §5.5).
"""

import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from smartesp.contracts import Person, PersonLink, VoiceSample

FILE = "person.json"
MAX_NAME = 40
_ID = re.compile(r"^[0-9a-f]{8}$")
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f/\\]")  # управляющие символы и разделители пути

_log = logging.getLogger(__name__)


def clean_name(name: str, taken: list[str]) -> str:
    """Имя без лишних пробелов; пусто, длиннее MAX_NAME, «/», «\\», «.», «..» или занято — ValueError.

    Имя идёт в промпт и в _meta.person (коннекторы делают из него папку), поэтому одна строка
    без разделителей пути. taken — имена других людей (сравниваются без учёта регистра).
    """
    clean = " ".join(name.split())
    if not clean or len(clean) > MAX_NAME:
        raise ValueError(f"имя от 1 до {MAX_NAME} символов")
    if _FORBIDDEN.search(clean) or clean in (".", ".."):
        raise ValueError("в имени не может быть «/», «\\» и служебных символов")
    if clean.casefold() in (t.casefold() for t in taken):
        raise ValueError(f"человек «{clean}» уже есть")
    return clean


def new_id() -> str:
    """Новый id человека или образца: 8 шестнадцатеричных знаков."""
    return uuid.uuid4().hex[:8]


def _sample(raw: dict[str, Any]) -> VoiceSample:
    return VoiceSample(
        id=str(raw["id"]),
        at=float(raw["at"]),
        device_id=str(raw.get("device_id", "")),
        seconds=float(raw.get("seconds", 0.0)),
        peak_db=float(raw.get("peak_db", 0.0)),
        model=str(raw["model"]),
        embedding=tuple(float(x) for x in raw["embedding"]),
    )


def _person(raw: dict[str, Any]) -> Person:
    samples = tuple(_sample(s) for s in raw.get("samples", []))
    links = tuple(PersonLink(str(k["channel"]), str(k["account"])) for k in raw.get("links", []))
    return Person(str(raw["id"]), str(raw["name"]), float(raw["created_at"]), samples, links)


def _raw(person: Person) -> dict[str, object]:
    samples = [
        {
            "id": s.id,
            "at": s.at,
            "device_id": s.device_id,
            "seconds": s.seconds,
            "peak_db": s.peak_db,
            "model": s.model,
            "embedding": [round(x, 6) for x in s.embedding],
        }
        for s in person.samples
    ]
    links = [{"channel": k.channel, "account": k.account} for k in person.links]
    head = {"id": person.id, "name": person.name, "created_at": person.created_at}
    return {**head, "links": links, "samples": samples}


class PeopleStore:
    """Папка людей: по папке на человека (в ней может появиться и другое — заметки и т. п.)."""

    def __init__(self, root: Path) -> None:
        """root — <data>/people."""
        self._root = root

    def load(self) -> list[Person]:
        """Все люди по времени добавления; битый файл — предупреждение в журнал и пропуск."""
        if not self._root.is_dir():
            return []
        people: list[Person] = []
        for file in sorted(self._root.glob(f"*/{FILE}")):
            if not _ID.match(file.parent.name):
                continue
            try:
                people.append(_person(json.loads(file.read_text("utf-8"))))
            except (OSError, ValueError, KeyError, TypeError):
                _log.warning("Люди: файл %s не прочитан, пропущен", file, exc_info=True)
        return sorted(people, key=lambda p: p.created_at)

    def save(self, person: Person) -> None:
        """Пишет person.json атомарно (через временный файл) с правами 0600."""
        folder = self._root / person.id
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{FILE}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(_raw(person), out, ensure_ascii=False)
        tmp.replace(folder / FILE)

    def remove(self, person_id: str) -> None:
        """Удаляет папку человека целиком."""
        if _ID.match(person_id):
            shutil.rmtree(self._root / person_id, ignore_errors=True)
