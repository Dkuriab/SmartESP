"""Библиотека звуков в папке данных: желаемый набор каждой колонки (sounds.json) и файлы (<sha256>.pcm).

Звуки задаются только колонке. В sounds.json — все известные колонки (из настроек или хоть раз
подключавшиеся), у каждой — свои звуки по сигналу; сигнала нет — встроенный. Файлы, на которые
больше ничто не ссылается, удаляются.

Миграция: прежний общий слой «all» (звук для всех колонок) переносится в каждую известную колонку,
у которой по этому сигналу не было своего выбора (явный «встроенный» остаётся встроенным), и
удаляется. Пока известных колонок нет, он ждёт первой (remember) и переносится тогда.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from smartesp.contracts import SOUND_TONES, SoundRef, SoundTone

_log = logging.getLogger(__name__)
INDEX = "sounds.json"
SHA256 = re.compile(r"[0-9a-f]{64}")

type Choices = dict[str, SoundRef | None]  # сигнал → звук (None — явно встроенный, только в старом файле)


class SoundLibrary:
    """Наборы колонок и файлы звуков в folder (папка создаётся при первом изменении)."""

    def __init__(self, folder: Path, known: Iterable[str] = ()) -> None:
        """known — колонки из настроек: им переносится прежний общий слой."""
        self._folder = folder
        self._devices: dict[str, dict[str, SoundRef]] = {}
        self._legacy: dict[str, SoundRef] = {}  # прежний «all», ещё не перенесённый
        self._explicit: dict[str, set[str]] = {}  # старый файл: явный «встроенный» у колонки
        self._load()
        self._migrate(known)

    def devices(self) -> list[str]:
        """Колонки, у которых ядро помнит набор (известные)."""
        return list(self._devices)

    def sound(self, device_id: str, tone: SoundTone) -> SoundRef | None:
        """Желаемый звук сигнала колонки; None — встроенный."""
        return self._devices.get(device_id, {}).get(tone)

    def wanted(self, device_id: str, tone: SoundTone) -> str | None:
        """SHA-256 звука, который должен быть на колонке; None — встроенный."""
        sound = self.sound(device_id, tone)
        return sound.sha256 if sound is not None else None

    def remember(self, device_id: str) -> None:
        """Колонка известна (подключилась или есть в настройках): её набор хранится, даже пустой."""
        if device_id not in self._devices:
            self._devices[device_id] = {}
            self._migrate(())
            self._save()

    def add(self, pcm: bytes, name: str) -> SoundRef:
        """Кладёт готовый звук (PCM 16 кГц моно) в папку; назначает его assign."""
        sha = hashlib.sha256(pcm).hexdigest()
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._folder / f"{sha}.pcm"
        if not path.exists():
            _write(path, pcm)
        return SoundRef(sha, name[:120], round(len(pcm) / 32000, 2))

    def assign(self, tone: SoundTone, sound: SoundRef | None, device_id: str) -> None:
        """Звук сигнала колонки (None — встроенный)."""
        own = self._devices.setdefault(device_id, {})
        if sound is None:
            own.pop(tone, None)
        else:
            own[tone] = sound
        self._changed()

    def copy(self, source: str, targets: Iterable[str]) -> list[str]:
        """Набор колонки source целиком — колонкам targets (кроме неё самой); кому скопировано."""
        done = [d for d in dict.fromkeys(targets) if d != source]
        for device_id in done:
            self._devices[device_id] = dict(self._devices.get(source, {}))
        self._changed()
        return done

    def pcm(self, sha256: str) -> bytes | None:
        """Готовый звук по SHA-256; нет — None."""
        path = self._folder / f"{sha256}.pcm"
        return path.read_bytes() if SHA256.fullmatch(sha256) and path.is_file() else None

    def _changed(self) -> None:
        self._save()
        self._collect()

    def _migrate(self, known: Iterable[str]) -> None:
        """Переносит прежний общий слой в известные колонки (без своего выбора по сигналу)."""
        targets = set(known) | set(self._devices)
        if not self._legacy or not targets:
            return
        for device_id in targets:
            own = self._devices.setdefault(device_id, {})
            explicit = self._explicit.get(device_id, set())
            for tone, sound in self._legacy.items():
                if tone not in own and tone not in explicit:
                    own[tone] = sound
        _log.info("Общие звуки перенесены в колонки: %s", ", ".join(sorted(targets)))
        self._legacy = {}
        self._explicit = {}
        self._save()

    def _used(self) -> set[str]:
        sounds = [*self._legacy.values(), *(s for own in self._devices.values() for s in own.values())]
        return {sound.sha256 for sound in sounds}

    def _collect(self) -> None:
        """Удаляет файлы, на которые больше не ссылается ни одна колонка."""
        used = self._used()
        for path in self._folder.glob("*.pcm"):
            if path.stem not in used:
                path.unlink(missing_ok=True)

    def _save(self) -> None:
        data: dict[str, object] = {
            "devices": {d: {t: vars(s) for t, s in own.items()} for d, own in self._devices.items()}
        }
        if self._legacy:
            data["all"] = {tone: vars(sound) for tone, sound in self._legacy.items()}
        self._folder.mkdir(parents=True, exist_ok=True)
        _write(self._folder / INDEX, json.dumps(data, ensure_ascii=False, indent=2).encode())

    def _load(self) -> None:
        path = self._folder / INDEX
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            legacy = {t: _ref(v) for t, v in dict(data.get("all", {})).items() if t in SOUND_TONES}
            self._legacy = {t: ref for t, ref in legacy.items() if ref is not None}
            for device_id, own in dict(data.get("devices", {})).items():
                choices = _choices(own)
                self._devices[str(device_id)] = {t: s for t, s in choices.items() if s is not None}
                self._explicit[str(device_id)] = {t for t, s in choices.items() if s is None}
        except (ValueError, TypeError, AttributeError) as error:
            _log.warning("Наборы звуков не прочитаны (%s) — встроенные", error)


def _ref(value: Any) -> SoundRef | None:
    """Звук из sounds.json; неверный — None."""
    if not isinstance(value, dict) or not SHA256.fullmatch(str(value.get("sha256", ""))):  # pyright: ignore[reportUnknownMemberType]
        return None
    item: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
    return SoundRef(str(item["sha256"]), str(item.get("name", "")), float(item.get("duration_s", 0.0)))


def _choices(value: Any) -> Choices:
    """Звуки колонки из sounds.json: сигнал → звук или null (старый явный встроенный); неверные — мимо."""
    items: dict[Any, Any] = value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    return {t: _ref(v) for t, v in items.items() if t in SOUND_TONES and (v is None or _ref(v) is not None)}


def _write(path: Path, data: bytes) -> None:
    """Пишет файл целиком: сначала рядом, потом подмена (обрыв не оставит половину)."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)
