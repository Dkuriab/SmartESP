"""Библиотека: разбор настроек, поиск файлов в разрешённых папках, станции, описание."""

import random
from pathlib import Path

import pytest

from music_mcp.library import Library, LibraryError, parse_pairs


def make_folders(tmp_path: Path) -> dict[str, str]:
    for rel in (
        "Кино/Группа крови.mp3",
        "Кино/Звезда по имени Солнце.flac",
        "Jazz/Take_Five.m4a",
        "Jazz/cover.jpg",
    ):
        path = tmp_path / "music" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (tmp_path / "music" / ".hidden").mkdir()
    (tmp_path / "music" / ".hidden" / "secret.mp3").write_bytes(b"x")
    return {"MUSIC_FOLDERS": f"Моя музыка={tmp_path / 'music'};Пустая={tmp_path / 'нет'}"}


def test_parse_pairs_skips_broken() -> None:
    assert parse_pairs("а=1; б = 2 ;;без значения=;=x;мусор") == [("а", "1"), ("б", "2")]


def test_find_by_words_in_folders_and_names(tmp_path: Path) -> None:
    library = Library(make_folders(tmp_path))
    assert [t.title for t in library.find("")] == ["Take_Five", "Группа крови", "Звезда по имени Солнце"]
    assert [t.title for t in library.find("кино солнце")] == ["Звезда по имени Солнце"]
    assert [t.title for t in library.find("take five")] == ["Take_Five"]  # «_» — пробел
    assert {t.folder for t in library.find("")} == {"Моя музыка"}
    with pytest.raises(LibraryError, match="по запросу «Битлз»"):
        library.find("Битлз")


def test_shuffle_keeps_all(tmp_path: Path) -> None:
    library = Library(make_folders(tmp_path))
    shuffled = library.find("", shuffle=True, rng=random.Random(3))
    assert sorted(t.title for t in shuffled) == sorted(t.title for t in library.find(""))


def test_no_folders_and_stations() -> None:
    library = Library({"MUSIC_RADIO": "Джаз FM=https://j/1;Рок=https://r/2"})
    with pytest.raises(LibraryError, match="Папки"):
        library.find("")
    assert library.station("") == ("Джаз FM", "https://j/1")
    assert library.station("рок") == ("Рок", "https://r/2")
    with pytest.raises(LibraryError, match="Есть: Джаз FM, Рок"):
        library.station("классика")
    with pytest.raises(LibraryError, match="Радиостанции"):
        Library({}).station("")


def test_describe_and_mac_device(tmp_path: Path) -> None:
    library = Library({**make_folders(tmp_path), "MUSIC_MAC_DEVICE": "Loopback"})
    text = library.describe()
    assert "Моя музыка (3 файлов)" in text and "Пустая (0 файлов)" in text and "«Loopback»" in text
    assert Library({}).mac_device == "BlackHole"
