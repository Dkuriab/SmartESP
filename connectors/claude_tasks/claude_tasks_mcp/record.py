"""Запись журнала: одна задача для Claude Code."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Status = Literal["running", "done", "failed", "cancelled"]
STATUSES: tuple[Status, ...] = ("running", "done", "failed", "cancelled")


@dataclass
class TaskRecord:
    """Задача: имя для речи, текст, папка, состояние, время, короткий итог или причина ошибки.

    `denials` — сколько действий Claude Code отклонил: «готово с отказами».
    """

    id: str
    name: str
    prompt: str
    folder: str
    person: str | None
    status: Status
    started: datetime
    finished: datetime | None = None
    summary: str = ""
    error: str = ""
    denials: int = 0

    def to_json(self) -> dict[str, Any]:
        """Словарь для JSON-файла журнала."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "folder": self.folder,
            "person": self.person,
            "status": self.status,
            "started": self.started.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None,
            "summary": self.summary,
            "error": self.error,
            "denials": self.denials,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "TaskRecord":
        """Запись из словаря журнала; неверное — ValueError/KeyError/TypeError."""
        status = raw["status"]
        if status not in STATUSES:
            raise ValueError(f"неизвестное состояние {status!r}")
        person = raw.get("person")
        finished = raw.get("finished")
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            prompt=str(raw["prompt"]),
            folder=str(raw["folder"]),
            person=person if isinstance(person, str) else None,
            status=status,
            started=datetime.fromisoformat(raw["started"]),
            finished=datetime.fromisoformat(finished) if isinstance(finished, str) else None,
            summary=str(raw.get("summary", "")),
            error=str(raw.get("error", "")),
            denials=int(raw.get("denials", 0)),
        )
