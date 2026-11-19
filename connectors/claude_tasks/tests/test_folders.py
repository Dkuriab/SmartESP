"""Разрешённые папки: по имени, подпапка, отказ всему, что ведёт наружу."""

from pathlib import Path

import pytest

from claude_tasks_mcp.folders import FolderError, resolve_folder


@pytest.fixture
def roots(tmp_path: Path) -> tuple[tuple[str, Path], ...]:
    for sub in ("repo/core", "notes", "secret"):
        (tmp_path / sub).mkdir(parents=True)
    real = tmp_path.resolve()
    return (("smartesp", real / "repo"), ("Заметки", real / "notes"))


def test_no_folders_configured() -> None:
    with pytest.raises(FolderError, match="Не настроены папки для задач Клода"):
        resolve_folder((), "")


def test_empty_means_first(roots: tuple[tuple[str, Path], ...]) -> None:
    assert resolve_folder(roots, "  ") == ("smartesp", roots[0][1])


def test_by_name_case_insensitive(roots: tuple[tuple[str, Path], ...]) -> None:
    assert resolve_folder(roots, "заметки") == ("Заметки", roots[1][1])


def test_subfolder_by_name_and_absolute(roots: tuple[tuple[str, Path], ...]) -> None:
    core = roots[0][1] / "core"
    assert resolve_folder(roots, "smartesp/core") == ("smartesp/core", core)
    assert resolve_folder(roots, str(core)) == ("smartesp/core", core)
    assert resolve_folder(roots, str(roots[1][1])) == ("Заметки", roots[1][1])


def test_unknown_name(roots: tuple[tuple[str, Path], ...]) -> None:
    with pytest.raises(FolderError, match="Нет папки «работа». Есть: smartesp, Заметки."):
        resolve_folder(roots, "работа")


@pytest.mark.parametrize("bad", ["smartesp/../secret", "../secret", "smartesp/../../", "/etc", "~"])
def test_path_traversal_rejected(roots: tuple[tuple[str, Path], ...], bad: str) -> None:
    with pytest.raises(FolderError):
        resolve_folder(roots, bad)


def test_absolute_traversal_rejected(roots: tuple[tuple[str, Path], ...], tmp_path: Path) -> None:
    with pytest.raises(FolderError, match="не из разрешённых"):
        resolve_folder(roots, f"{roots[0][1]}/../secret")


def test_symlink_outside_rejected(roots: tuple[tuple[str, Path], ...], tmp_path: Path) -> None:
    (roots[0][1] / "escape").symlink_to(tmp_path / "secret")
    with pytest.raises(FolderError, match="не из разрешённых"):
        resolve_folder(roots, "smartesp/escape")


def test_sibling_with_common_prefix_rejected(roots: tuple[tuple[str, Path], ...], tmp_path: Path) -> None:
    (tmp_path / "repo-evil").mkdir()
    with pytest.raises(FolderError, match="не из разрешённых"):
        resolve_folder(roots, str(tmp_path / "repo-evil"))


def test_missing_folder(roots: tuple[tuple[str, Path], ...]) -> None:
    with pytest.raises(FolderError, match="нет на диске"):
        resolve_folder(roots, "smartesp/nope")
    gone = (("старое", roots[0][1] / "gone"),)
    with pytest.raises(FolderError, match="нет на диске"):
        resolve_folder(gone, "")


def test_file_is_not_a_folder(roots: tuple[tuple[str, Path], ...]) -> None:
    (roots[0][1] / "file.txt").write_text("x")
    with pytest.raises(FolderError, match="нет на диске"):
        resolve_folder(roots, "smartesp/file.txt")
