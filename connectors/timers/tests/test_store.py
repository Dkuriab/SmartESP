"""Файлы состояния: человекочитаемо, атомарно, испорченное пропускается."""

import json
from pathlib import Path

import pytest

from tests.conftest import START
from timers_mcp.entry import Entry
from timers_mcp.store import Store, person_folder


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path)
    entry = Entry(kind="reminder", name="позвонить маме", due=START, person="гость")
    store.save("гость", [entry])
    text = (tmp_path / "гость" / "timers.json").read_text(encoding="utf-8")
    assert "позвонить маме" in text
    assert json.loads(text)["items"][0]["due"] == "2026-11-19T14:00:00+03:00"
    assert store.load_all() == [entry]
    assert [p.name for p in (tmp_path / "гость").iterdir()] == ["timers.json"]


def test_corrupt_file_is_skipped(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.save(None, [Entry(kind="timer", name="чай", due=START, person=None)])
    (tmp_path / "гость").mkdir()
    (tmp_path / "гость" / "timers.json").write_text("{не json", encoding="utf-8")
    assert [e.name for e in store.load_all()] == ["чай"]


def test_person_folder() -> None:
    assert person_folder(None) == "home"
    assert person_folder("  ") == "home"
    assert person_folder(" гость ") == "гость"
    for bad in ("..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            person_folder(bad)
