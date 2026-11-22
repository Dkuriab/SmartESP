"""Записи фраз на диске: recordings/<фраза>/<человек>/<n>.wav (16 кГц, моно, s16le)."""

from __future__ import annotations

import math
import re
import wave
from array import array
from pathlib import Path

from smartesp.contracts import PhraseRecording, TrainingLookupError

SAMPLE_RATE = 16000
_NAME = re.compile(r"^\d{4}\.wav$")
_UNSAFE = re.compile(r"[^\w\- ,!?]+")


def folder_name(text: str) -> str:
    """Имя папки из фразы или имени: без «/» и точек в начале; пусто — «_»."""
    name = _UNSAFE.sub("", text.strip()).strip().lstrip(".")
    return name[:60] or "_"


def peak_db(pcm: bytes) -> float:
    """Пик громкости PCM s16le в дБ от полной шкалы (тишина — −96)."""
    samples = array("h", pcm[: len(pcm) - len(pcm) % 2])
    peak = max((abs(s) for s in samples), default=0)
    return round(20 * math.log10(peak / 32768), 1) if peak else -96.0


class RecordingStore:
    """Записи одного набора в папке root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _dir(self, phrase: str, person: str) -> Path:
        return self._root / folder_name(phrase) / folder_name(person)

    def counts(self, phrase: str) -> dict[str, int]:
        """{папка человека: число записей} для фразы."""
        base = self._root / folder_name(phrase)
        if not base.is_dir():
            return {}
        people = {
            p.name: sum(1 for f in p.iterdir() if _NAME.match(f.name))
            for p in sorted(base.iterdir())
            if p.is_dir()
        }
        return {name: n for name, n in people.items() if n}

    def save(self, phrase: str, person: str, pcm: bytes) -> PhraseRecording:
        """Сохраняет новую запись следующим номером."""
        folder = self._dir(phrase, person)
        folder.mkdir(parents=True, exist_ok=True)
        numbers = [int(f.name[:4]) for f in folder.iterdir() if _NAME.match(f.name)]
        path = folder / f"{max(numbers, default=0) + 1:04d}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes(pcm)
        return PhraseRecording(path.name, round(len(pcm) / 2 / SAMPLE_RATE, 2), peak_db(pcm))

    def list(self, phrase: str, person: str) -> list[PhraseRecording]:
        """Записи фразы человека по номеру."""
        folder = self._dir(phrase, person)
        files = sorted(f for f in folder.iterdir() if _NAME.match(f.name)) if folder.is_dir() else []
        return [_info(f) for f in files]

    def file(self, phrase: str, person: str, name: str) -> Path:
        """Путь к записи; имя не «NNNN.wav» или файла нет — TrainingLookupError."""
        path = self._dir(phrase, person) / name
        if not _NAME.match(name) or not path.is_file():
            raise TrainingLookupError(f"нет записи {name}")
        return path


def _info(path: Path) -> PhraseRecording:
    with wave.open(str(path), "rb") as src:
        pcm = src.readframes(src.getnframes())
        rate = src.getframerate() or SAMPLE_RATE
    return PhraseRecording(path.name, round(len(pcm) / 2 / rate, 2), peak_db(pcm))
