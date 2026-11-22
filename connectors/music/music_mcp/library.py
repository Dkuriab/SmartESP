"""Что можно играть: файлы из разрешённых папок, станции радио, устройство «звук Mac» (из настроек).

Папки — «имя=путь;…» (MUSIC_FOLDERS), станции — «имя=ссылка;…» (MUSIC_RADIO). За пределы папок
коннектор не ходит: путь берётся только из обхода разрешённых папок, не из слов модели.
"""

from __future__ import annotations

import os
import random
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

AUDIO_SUFFIXES = frozenset(
    {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus", ".aif", ".aiff"}
)
MAX_SCAN = 20000  # файлов за один обход: больше — не смотрим
MAX_QUEUE = 500
DEFAULT_DEVICE = "BlackHole"


class LibraryError(Exception):
    """Понятная человеку ошибка (нет папок, ничего не нашлось)."""


@dataclass(frozen=True)
class Track:
    """Файл: полный путь, название (имя файла), где лежит (имя папки и подпапки — для поиска) и имя
    разрешённой папки."""

    path: str
    title: str
    place: str
    folder: str


def parse_pairs(value: str) -> list[tuple[str, str]]:
    """«имя=значение;…» → пары; записи без «=» или с пустой частью пропускаются."""
    pairs: list[tuple[str, str]] = []
    for item in value.split(";"):
        name, sep, rest = item.partition("=")
        if sep and name.strip() and rest.strip():
            pairs.append((name.strip(), rest.strip()))
    return pairs


def normalize(text: str) -> str:
    """Для поиска: без регистра, ё = е, «_» и «-» — пробелы."""
    return text.casefold().replace("ё", "е").replace("_", " ").replace("-", " ")


class Library:
    """Настройки коннектора: папки, станции, устройство звука Mac."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.folders = [
            (name, Path(path).expanduser()) for name, path in parse_pairs(env.get("MUSIC_FOLDERS", ""))
        ]
        self.stations = parse_pairs(env.get("MUSIC_RADIO", ""))
        self.mac_device = env.get("MUSIC_MAC_DEVICE", "").strip() or DEFAULT_DEVICE

    def tracks(self) -> list[Track]:
        """Все звуковые файлы разрешённых папок (не больше MAX_SCAN), по пути."""
        found: list[Track] = []
        for name, root in self.folders:
            if not root.is_dir():
                continue
            for folder, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for file in sorted(files):
                    path = Path(folder) / file
                    if path.suffix.lower() in AUDIO_SUFFIXES and not file.startswith("."):
                        place = " ".join([name, *path.relative_to(root).parent.parts])
                        found.append(Track(str(path), path.stem, place, name))
                        if len(found) >= MAX_SCAN:
                            return found
        return found

    def find(self, query: str, *, shuffle: bool = False, rng: random.Random | None = None) -> list[Track]:
        """Файлы, где в имени или папках есть все слова запроса (пусто — все); не больше MAX_QUEUE."""
        if not self.folders:
            raise LibraryError("Папки с музыкой не заданы в настройках коннектора «Музыка на колонках».")
        words = normalize(query).split()
        matched = [t for t in self.tracks() if all(w in normalize(f"{t.place} {t.title}") for w in words)]
        if not matched:
            what = f" по запросу «{query}»" if words else ""
            raise LibraryError(f"Не нашлось музыки{what} в папках: {', '.join(n for n, _ in self.folders)}.")
        if shuffle:
            (rng or random.Random()).shuffle(matched)
        return matched[:MAX_QUEUE]

    def station(self, name: str) -> tuple[str, str]:
        """Станция по имени или его части (пусто — первая): (имя, ссылка)."""
        if not self.stations:
            raise LibraryError("Радиостанции не заданы в настройках коннектора «Музыка на колонках».")
        wanted = normalize(name).strip()
        if not wanted:
            return self.stations[0]
        for station in self.stations:
            if wanted in normalize(station[0]) or normalize(station[0]) in wanted:
                return station
        names = ", ".join(n for n, _ in self.stations)
        raise LibraryError(f"Нет станции «{name}». Есть: {names}.")

    def describe(self) -> str:
        """Что есть: папки (с числом файлов), станции, звук Mac."""
        lines: list[str] = []
        if self.folders:
            counts: dict[str, int] = {}
            for track in self.tracks():
                counts[track.folder] = counts.get(track.folder, 0) + 1
            parts = [f"{name} ({counts.get(name, 0)} файлов)" for name, _ in self.folders]
            lines.append("Папки: " + ", ".join(parts) + ".")
        else:
            lines.append("Папки с музыкой не заданы.")
        stations = ", ".join(n for n, _ in self.stations)
        lines.append(f"Радио: {stations}." if stations else "Радиостанции не заданы.")
        lines.append(f"Звук Mac — с устройства «{self.mac_device}».")
        return " ".join(lines)
