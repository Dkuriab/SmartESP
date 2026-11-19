"""Файловое хранилище: нормализация имён и атомарная запись."""

import os
import re
import tempfile
from pathlib import Path

HOME_PERSON = "home"
_UNSAFE = re.compile(r"[/\\:\x00]")


def normalize_text(text: str) -> str:
    """Приводит строку к виду для сравнения: регистр, «ё», пробелы."""
    return " ".join(text.lower().replace("ё", "е").split())


def safe_name(raw: str) -> str:
    """Имя для файла или папки: нормализованное, без разделителей путей и ведущих точек.

    Возвращает пустую строку, если от имени ничего не осталось.
    """
    return normalize_text(_UNSAFE.sub(" ", raw)).lstrip(". ")


def person_root(data_dir: Path, person: str | None) -> Path:
    """Папка данных человека; без человека (или с неподходящим именем) — общая «home»."""
    name = safe_name(person) if person else ""
    return data_dir / (name or HOME_PERSON)


def read_text(path: Path) -> str:
    """Читает файл; нет файла — пустая строка."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def write_atomic(path: Path, text: str) -> None:
    """Пишет файл атомарно: временный файл рядом, затем rename.

    При ошибке исходный файл остаётся нетронутым, временный удаляется.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
