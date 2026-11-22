"""Библиотека звуков в папке данных: назначения владельца (sounds.json) и готовые файлы (<sha256>.pcm).

Назначение — для всех колонок или для одной; действует последнее: «для всех» сбрасывает выборы
отдельных колонок по этому сигналу. У колонки звук = её выбор (свой или явный встроенный), иначе
общий, иначе встроенный. Файлы, на которые больше ничто не ссылается, удаляются.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from smartesp.contracts import SOUND_TONES, SoundRef, SoundSource, SoundTone

_log = logging.getLogger(__name__)
INDEX = "sounds.json"
SHA256 = re.compile(r"[0-9a-f]{64}")

type Choices = dict[str, SoundRef | None]  # сигнал → звук (None — явно встроенный)


class SoundLibrary:
    """Назначения и файлы звуков в folder (папка создаётся при первом изменении)."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._common: dict[str, SoundRef] = {}
        self._devices: dict[str, Choices] = {}
        self._load()

    def common(self) -> dict[SoundTone, SoundRef | None]:
        """Общие звуки по сигналу; None — встроенный."""
        return {tone: self._common.get(tone) for tone in SOUND_TONES}

    def choice(self, device_id: str, tone: SoundTone) -> tuple[SoundSource, SoundRef | None]:
        """Откуда звук сигнала на колонке и какой он (None — встроенный)."""
        own = self._devices.get(device_id, {})
        if tone in own:
            sound = own[tone]
            return ("device" if sound is not None else "builtin"), sound
        sound = self._common.get(tone)
        return ("all" if sound is not None else "builtin"), sound

    def wanted(self, device_id: str, tone: SoundTone) -> str | None:
        """SHA-256 звука, который должен быть на колонке; None — встроенный."""
        sound = self.choice(device_id, tone)[1]
        return sound.sha256 if sound is not None else None

    def add(self, pcm: bytes, name: str) -> SoundRef:
        """Кладёт готовый звук (PCM 16 кГц моно) в папку; назначает его assign."""
        sha = hashlib.sha256(pcm).hexdigest()
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._folder / f"{sha}.pcm"
        if not path.exists():
            _write(path, pcm)
        return SoundRef(sha, name[:120], round(len(pcm) / 32000, 2))

    def assign(self, tone: SoundTone, sound: SoundRef | None, device_id: str | None) -> None:
        """Звук сигнала (None — встроенный): всем колонкам (сбрасывает их выборы) или одной."""
        if device_id is None:
            if sound is None:
                self._common.pop(tone, None)
            else:
                self._common[tone] = sound
            for own in self._devices.values():
                own.pop(tone, None)
        else:
            self._devices.setdefault(device_id, {})[tone] = sound
        self._devices = {device: own for device, own in self._devices.items() if own}
        self._save()
        self._collect()

    def pcm(self, sha256: str) -> bytes | None:
        """Готовый звук по SHA-256; нет — None."""
        path = self._folder / f"{sha256}.pcm"
        return path.read_bytes() if SHA256.fullmatch(sha256) and path.is_file() else None

    def _used(self) -> set[str]:
        sounds = [*self._common.values(), *(s for own in self._devices.values() for s in own.values())]
        return {sound.sha256 for sound in sounds if sound is not None}

    def _collect(self) -> None:
        """Удаляет файлы, на которые больше не ссылается ни одно назначение."""
        used = self._used()
        for path in self._folder.glob("*.pcm"):
            if path.stem not in used:
                path.unlink(missing_ok=True)

    def _save(self) -> None:
        data = {
            "all": {tone: vars(sound) for tone, sound in self._common.items()},
            "devices": {
                device: {tone: vars(s) if s is not None else None for tone, s in own.items()}
                for device, own in self._devices.items()
            },
        }
        self._folder.mkdir(parents=True, exist_ok=True)
        _write(self._folder / INDEX, json.dumps(data, ensure_ascii=False, indent=2).encode())

    def _load(self) -> None:
        path = self._folder / INDEX
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            common = {t: _ref(v) for t, v in dict(data.get("all", {})).items() if t in SOUND_TONES}
            self._common = {t: ref for t, ref in common.items() if ref is not None}
            devices = dict(data.get("devices", {})).items()
            self._devices = {str(d): _choices(own) for d, own in devices if _choices(own)}
        except (ValueError, TypeError, AttributeError) as error:
            _log.warning("Назначения звуков не прочитаны (%s) — встроенные", error)


def _ref(value: Any) -> SoundRef | None:
    """Звук из sounds.json; неверный — None."""
    if not isinstance(value, dict) or not SHA256.fullmatch(str(value.get("sha256", ""))):  # pyright: ignore[reportUnknownMemberType]
        return None
    item: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
    return SoundRef(str(item["sha256"]), str(item.get("name", "")), float(item.get("duration_s", 0.0)))


def _choices(value: Any) -> Choices:
    """Выборы колонки из sounds.json: сигнал → звук или null (встроенный); неверные — мимо."""
    items: dict[Any, Any] = value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    return {t: _ref(v) for t, v in items.items() if t in SOUND_TONES and (v is None or _ref(v) is not None)}


def _write(path: Path, data: bytes) -> None:
    """Пишет файл целиком: сначала рядом, потом подмена (обрыв не оставит половину)."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)
