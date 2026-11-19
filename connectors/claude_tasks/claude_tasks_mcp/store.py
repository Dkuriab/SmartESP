"""Журнал на диске: `<data>/<person>/tasks.json` и полные ответы `<person>/output/<id>.md`.

Запись атомарная: временный файл + rename. В журнале — последние `KEEP` задач человека,
ответы выпавших из журнала задач удаляются.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from claude_tasks_mcp.record import TaskRecord

FILE_NAME = "tasks.json"
OUTPUT_DIR = "output"
HOME = "home"
KEEP = 50

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


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Store:
    """Журнал задач по людям в человекочитаемом JSON."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def load_all(self) -> list[TaskRecord]:
        """Все задачи всех людей; испорченный файл пропускается с предупреждением в журнал."""
        records: list[TaskRecord] = []
        if not self._root.is_dir():
            return records
        for path in sorted(self._root.glob(f"*/{FILE_NAME}")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                records.extend(TaskRecord.from_json(item) for item in raw["tasks"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("пропускаю испорченный файл %s: %s", path, exc)
        return records

    def save(self, person: str | None, records: list[TaskRecord]) -> list[TaskRecord]:
        """Записывает последние `KEEP` задач человека; возвращает оставшиеся в журнале."""
        kept = records[-KEEP:]
        folder = self._root / person_folder(person)
        text = json.dumps({"tasks": [r.to_json() for r in kept]}, ensure_ascii=False, indent=2)
        _write_atomic(folder / FILE_NAME, text + "\n")
        for dropped in records[: len(records) - len(kept)]:
            (folder / OUTPUT_DIR / f"{dropped.id}.md").unlink(missing_ok=True)
        return kept

    def save_output(self, record: TaskRecord, text: str) -> None:
        """Сохраняет полный ответ Claude на задачу."""
        path = self._root / person_folder(record.person) / OUTPUT_DIR / f"{record.id}.md"
        _write_atomic(path, text)
