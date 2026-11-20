"""Доска таймеров: что идёт у каждого человека; каждое изменение сразу в файл."""

import logging
from datetime import datetime, timedelta

from timers_mcp.entry import Entry, Kind
from timers_mcp.phrases import DEFAULT_NAME
from timers_mcp.store import Store, person_folder

CANCEL_ALL = "все"

logger = logging.getLogger(__name__)


class Board:
    """Таймеры и напоминания в памяти, записанные в `Store`."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._entries: list[Entry] = []

    def load(self, now: datetime) -> list[Entry]:
        """Читает файлы при старте. Возвращает пропущенные за простой (и убирает их)."""
        self._entries = self._store.load_all()
        missed = [e for e in self._entries if e.due <= now]
        self._remove(missed)
        return sorted(missed, key=lambda e: e.due)

    def start_timer(self, person: str | None, seconds: float, name: str, now: datetime) -> Entry:
        """Ставит таймер; повтор имени получает номер: «таймер 2»."""
        unique = self._unique_name(person, name.strip() or DEFAULT_NAME)
        return self._add("timer", unique, now + timedelta(seconds=seconds), person)

    def add_reminder(self, person: str | None, due: datetime, text: str) -> Entry:
        """Ставит напоминание на момент `due`."""
        return self._add("reminder", text.strip(), due, person)

    def all(self) -> list[Entry]:
        """Все записи всех людей по времени срабатывания."""
        return sorted(self._entries, key=lambda e: e.due)

    def active(self, person: str | None) -> list[Entry]:
        """Записи человека по времени срабатывания."""
        key = person_folder(person)
        return sorted((e for e in self._entries if person_folder(e.person) == key), key=lambda e: e.due)

    def cancel(self, person: str | None, name: str) -> list[Entry]:
        """Отменяет по имени (без учёта регистра) или все («все»). Возвращает отменённые."""
        mine = self.active(person)
        wanted = name.strip().casefold()
        removed = mine if wanted == CANCEL_ALL else [e for e in mine if e.name.casefold() == wanted][:1]
        self._remove(removed)
        return removed

    def pop_due(self, now: datetime) -> list[Entry]:
        """Забирает сработавшие к `now` записи (из памяти и файлов).

        Не удалось записать файл — записи всё равно возвращаются, чтобы прозвучать
        (после перезапуска они объявятся ещё раз как пропущенные).
        """
        due = sorted((e for e in self._entries if e.due <= now), key=lambda e: e.due)
        try:
            self._remove(due)
        except OSError:
            logger.exception("не удалось записать файл таймеров")
        return due

    def _add(self, kind: Kind, name: str, due: datetime, person: str | None) -> Entry:
        entry = Entry(kind=kind, name=name, due=due, person=_clean(person))
        self._entries.append(entry)
        self._save({person_folder(person)})
        return entry

    def _unique_name(self, person: str | None, base: str) -> str:
        taken = {e.name.casefold() for e in self.active(person) if e.kind == "timer"}
        if base.casefold() not in taken:
            return base
        number = 2
        while f"{base} {number}".casefold() in taken:
            number += 1
        return f"{base} {number}"

    def _remove(self, entries: list[Entry]) -> None:
        if not entries:
            return
        gone = {id(e) for e in entries}
        self._entries = [e for e in self._entries if id(e) not in gone]
        self._save({person_folder(e.person) for e in entries})

    def _save(self, folders: set[str]) -> None:
        for folder in folders:
            mine = [e for e in self._entries if person_folder(e.person) == folder]
            self._store.save(None if folder == person_folder(None) else folder, mine)


def _clean(person: str | None) -> str | None:
    """Человек как в `_meta.person`: пустая строка — нет человека."""
    return person.strip() if person and person.strip() else None
