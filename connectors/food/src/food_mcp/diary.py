"""Дневник съеденного: `diary/YYYY-MM.jsonl`, запись — строка JSON."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .food import Food
from .storage import read_text, write_atomic

TIME_FORMAT = "%Y-%m-%dT%H:%M"


@dataclass(frozen=True)
class Entry:
    """Запись дневника: что, когда, сколько граммов (и штук), откуда калорийность.

    `seq` — порядковый номер добавления (для «убери последнее»).
    """

    seq: int
    time: datetime
    food: Food
    grams: float
    count: int
    source: str

    def _part(self, per_100g: float) -> float:
        return per_100g * self.grams / 100

    @property
    def kcal(self) -> float:
        return self._part(self.food.kcal_100g)

    @property
    def protein(self) -> float:
        return self._part(self.food.protein)

    @property
    def fat(self) -> float:
        return self._part(self.food.fat)

    @property
    def carbs(self) -> float:
        return self._part(self.food.carbs)

    def to_json(self) -> str:
        """Строка файла: итоги записи рядом с продуктом на 100 г — файл читается глазами."""
        data: dict[str, Any] = {
            "seq": self.seq,
            "time": self.time.strftime(TIME_FORMAT),
            "name": self.food.name,
            "grams": self.grams,
            "count": self.count,
            "kcal": round(self.kcal, 2),
            "protein": round(self.protein, 2),
            "fat": round(self.fat, 2),
            "carbs": round(self.carbs, 2),
            "source": self.source,
            "food": self.food.to_dict(),
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Entry":
        raw = json.loads(line)
        return cls(
            seq=int(raw["seq"]),
            time=datetime.strptime(raw["time"], TIME_FORMAT),
            food=Food.from_dict(raw["food"]),
            grams=float(raw["grams"]),
            count=int(raw.get("count", 0)),
            source=str(raw.get("source", "")),
        )


def _folder(root: Path) -> Path:
    return root / "diary"


def _month_path(root: Path, when: datetime) -> Path:
    return _folder(root) / f"{when:%Y-%m}.jsonl"


def _read(path: Path) -> list[Entry]:
    entries: list[Entry] = []
    for line in read_text(path).splitlines():
        try:
            entries.append(Entry.from_json(line))
        except (ValueError, KeyError, TypeError):
            continue  # испорченная строка не мешает остальным
    return entries


def _write(path: Path, entries: list[Entry]) -> None:
    if entries:
        write_atomic(path, "".join(e.to_json() + "\n" for e in entries))
    else:
        path.unlink(missing_ok=True)


def load_all(root: Path) -> list[Entry]:
    """Все записи по времени еды."""
    folder = _folder(root)
    if not folder.is_dir():
        return []
    entries = [e for path in sorted(folder.glob("*.jsonl")) for e in _read(path)]
    return sorted(entries, key=lambda e: (e.time, e.seq))


def add(root: Path, when: datetime, food: Food, grams: float, count: int, source: str) -> Entry:
    """Добавляет запись в файл её месяца (атомарно) и возвращает её."""
    seq = max((e.seq for e in load_all(root)), default=0) + 1
    entry = Entry(seq, when.replace(second=0, microsecond=0), food, grams, count, source)
    path = _month_path(root, entry.time)
    _write(path, [*_read(path), entry])
    return entry


def pop_last(root: Path) -> Entry | None:
    """Убирает последнюю добавленную запись; дневник пуст — None."""
    entries = load_all(root)
    if not entries:
        return None
    last = max(entries, key=lambda e: e.seq)
    path = _month_path(root, last.time)
    _write(path, [e for e in _read(path) if e.seq != last.seq])
    return last


def on_day(root: Path, day: date) -> list[Entry]:
    """Записи за день по времени."""
    return [e for e in load_all(root) if e.time.date() == day]
