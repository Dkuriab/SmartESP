"""Заметки: файл `notes/YYYY-MM-DD.md`, заметка — абзац «ЧЧ:ММ текст»."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .storage import normalize_text, read_text, write_atomic

MAX_FOUND = 5


@dataclass(frozen=True)
class Note:
    """Найденная заметка: день, абзац целиком (с временем) и текст для показа."""

    day: str
    paragraph: str

    @property
    def text(self) -> str:
        return self.paragraph.split(" ", 1)[1] if " " in self.paragraph else self.paragraph

    def label(self) -> str:
        return f"{self.day} {self.paragraph.split(' ', 1)[0]} — {self.text}"


def _folder(root: Path) -> Path:
    return root / "notes"


def _paragraphs(path: Path) -> list[str]:
    return [p.strip() for p in read_text(path).split("\n\n") if p.strip()]


def add(root: Path, text: str, now: datetime) -> None:
    """Дописывает заметку в файл сегодняшнего дня."""
    path = _folder(root) / f"{now:%Y-%m-%d}.md"
    paragraphs = _paragraphs(path)
    paragraphs.append(f"{now:%H:%M} {' '.join(text.split())}")
    write_atomic(path, "\n\n".join(paragraphs) + "\n")


def find(root: Path, query: str) -> list[Note]:
    """Все совпадения, от новых к старым (порядок: день по убыванию, внутри дня с конца)."""
    needle = normalize_text(query)
    folder = _folder(root)
    if not needle or not folder.is_dir():
        return []
    found: list[Note] = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        for paragraph in reversed(_paragraphs(path)):
            if needle in normalize_text(paragraph.split(" ", 1)[-1]):
                found.append(Note(path.stem, paragraph))
    return found


def delete(root: Path, note: Note) -> None:
    """Удаляет заметку; опустевший файл дня убирается."""
    path = _folder(root) / f"{note.day}.md"
    paragraphs = _paragraphs(path)
    if note.paragraph in paragraphs:
        paragraphs.remove(note.paragraph)
    if paragraphs:
        write_atomic(path, "\n\n".join(paragraphs) + "\n")
    else:
        path.unlink(missing_ok=True)
