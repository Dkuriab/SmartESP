"""Запись таймера или напоминания и её вид в файле."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Kind = Literal["timer", "reminder"]


@dataclass(frozen=True)
class Entry:
    """Таймер или напоминание одного человека.

    `name` — имя таймера или текст напоминания; `due` — когда сработает (с часовым
    поясом); `person` — чьё (None — общее «дом»).
    """

    kind: Kind
    name: str
    due: datetime
    person: str | None

    @property
    def task_id(self) -> str:
        """Постоянный id записи для задачи «В работе» ядра: вид, человек, имя и время."""
        return f"{self.kind}:{self.person or ''}:{self.name}:{self.due.isoformat()}"

    def to_json(self) -> dict[str, Any]:
        """Словарь для файла (время — ISO с часовым поясом)."""
        return {"kind": self.kind, "name": self.name, "due": self.due.isoformat(), "person": self.person}

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "Entry":
        """Запись из словаря файла; кривые данные — ValueError/KeyError/TypeError."""
        kind = raw["kind"]
        if kind not in ("timer", "reminder"):
            raise ValueError(f"неизвестный вид записи: {kind!r}")
        due = datetime.fromisoformat(str(raw["due"]))
        if due.tzinfo is None:
            raise ValueError("время без часового пояса")
        person = raw.get("person")
        return Entry(
            kind=kind, name=str(raw["name"]), due=due, person=str(person) if person is not None else None
        )
