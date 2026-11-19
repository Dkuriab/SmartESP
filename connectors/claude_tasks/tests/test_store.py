"""Журнал на диске: чтение, испорченный файл, предел длины, неверное имя человека."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_tasks_mcp.record import TaskRecord
from claude_tasks_mcp.store import KEEP, Store, person_folder

MOMENT = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)


def _record(i: int, person: str | None = None) -> TaskRecord:
    return TaskRecord(f"id{i}", f"задача {i}", "текст", "smartesp", person, "done", MOMENT, MOMENT)


def test_round_trip_and_corrupted_file_skipped(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.save("гость", [_record(1, "гость")])
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "tasks.json").write_text("{не json", encoding="utf-8")
    assert store.load_all() == [_record(1, "гость")]


def test_keeps_last_records_and_drops_their_output(tmp_path: Path) -> None:
    store = Store(tmp_path)
    records = [_record(i) for i in range(KEEP + 1)]
    store.save_output(records[0], "старый ответ")
    kept = store.save(None, records)
    assert kept == records[1:]
    assert not (tmp_path / "home" / "output" / "id0.md").exists()
    assert len(store.load_all()) == KEEP


@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a\\b"])
def test_bad_person(bad: str) -> None:
    with pytest.raises(ValueError):
        person_folder(bad)
