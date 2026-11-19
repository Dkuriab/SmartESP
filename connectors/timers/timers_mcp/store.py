"""Файлы состояния: `<data>/<person>/timers.json`, запись атомарная."""

import json
import logging
import os
import tempfile
from pathlib import Path

from timers_mcp.entry import Entry

FILE_NAME = "timers.json"
HOME = "home"

logger = logging.getLogger(__name__)


def person_folder(person: str | None) -> str:
    """Имя папки человека; None или пусто — общая «дом» (`home`).

    Имя с разделителями пути или «.»/«..» — ValueError (данные только внутри папки данных).
    """
    if person is None or not person.strip():
        return HOME
    name = person.strip()
    if name in (".", "..") or any(ch in name for ch in "/\\\0"):
        raise ValueError("Неверное имя человека.")
    return name


class Store:
    """Хранит записи по людям в человекочитаемом JSON."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def load_all(self) -> list[Entry]:
        """Все записи всех людей; испорченный файл пропускается с предупреждением в журнал."""
        entries: list[Entry] = []
        if not self._root.is_dir():
            return entries
        for path in sorted(self._root.glob(f"*/{FILE_NAME}")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries.extend(Entry.from_json(item) for item in raw["items"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("пропускаю испорченный файл %s: %s", path, exc)
        return entries

    def save(self, person: str | None, entries: list[Entry]) -> None:
        """Записывает записи человека атомарно: временный файл + rename."""
        folder = self._root / person_folder(person)
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"items": [e.to_json() for e in entries]}, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".timers-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, folder / FILE_NAME)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
