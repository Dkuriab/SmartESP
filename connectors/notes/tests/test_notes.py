"""Тесты инструментов заметок."""

from pathlib import Path

from .conftest import Caller


async def test_note_add_writes_dated_file(call: Caller, data_dir: Path) -> None:
    out = await call("note_add", {"text": "Позвонить врачу"})
    assert out == "Записала."
    await call("note_add", {"text": "Купить\nподарок"})
    text = (data_dir / "home" / "notes" / "2026-11-19.md").read_text()
    assert text == "10:32 Позвонить врачу\n\n10:32 Купить подарок\n"


async def test_note_add_empty(call: Caller) -> None:
    assert await call("note_add", {"text": "  "}) == "Пустую заметку не записываю."


async def test_notes_find(call: Caller) -> None:
    await call("note_add", {"text": "Ключи в Ёлочке"})
    out = await call("notes_find", {"query": "елочке"})
    assert out == "Нашла: 2026-11-19 10:32 — Ключи в Ёлочке."
    assert await call("notes_find", {"query": "пароль"}) == "Заметок про «пароль» не нашла."


async def test_notes_find_limit_five_latest(call: Caller, data_dir: Path) -> None:
    notes = data_dir / "home" / "notes"
    notes.mkdir(parents=True)
    for day in range(1, 8):
        (notes / f"2026-11-0{day}.md").write_text(f"09:00 дело {day}\n")
    out = await call("notes_find", {"query": "дело"})
    assert out.count("—") == 5
    assert "дело 7" in out and "дело 3" in out and "дело 2" not in out
    assert out.index("дело 7") < out.index("дело 3")


async def test_note_delete_single(call: Caller, data_dir: Path) -> None:
    await call("note_add", {"text": "позвонить врачу"})
    await call("note_add", {"text": "купить хлеб"})
    assert await call("note_delete", {"query": "врачу"}) == "Удалила заметку: позвонить врачу."
    text = (data_dir / "home" / "notes" / "2026-11-19.md").read_text()
    assert text == "10:32 купить хлеб\n"


async def test_note_delete_last_removes_file(call: Caller, data_dir: Path) -> None:
    await call("note_add", {"text": "раз"})
    await call("note_delete", {"query": "раз"})
    assert not (data_dir / "home" / "notes" / "2026-11-19.md").exists()


async def test_note_delete_ambiguous_and_missing(call: Caller) -> None:
    await call("note_add", {"text": "купить хлеб"})
    await call("note_add", {"text": "купить молоко"})
    out = await call("note_delete", {"query": "купить"})
    assert "несколько" in out and "хлеб" in out and "молоко" in out
    assert await call("note_delete", {"query": "пароль"}) == "Заметок про «пароль» не нашла."
    assert "купить хлеб" in await call("notes_find", {"query": "хлеб"})


async def test_notes_per_person(call: Caller) -> None:
    await call("note_add", {"text": "секрет"}, person="мама")
    assert await call("notes_find", {"query": "секрет"}) == "Заметок про «секрет» не нашла."
    assert "секрет" in await call("notes_find", {"query": "секрет"}, person="мама")
