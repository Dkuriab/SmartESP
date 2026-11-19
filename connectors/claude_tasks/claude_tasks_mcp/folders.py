"""Выбор папки для задачи: только разрешённые папки и их подпапки.

Любой путь сначала разворачивается через realpath (символьные ссылки, «..»), и только
потом сверяется со списком — так ни ссылка, ни «..» не выводят за разрешённое.
"""

import os
from pathlib import Path

NO_FOLDERS = "Не настроены папки для задач Клода."

Folders = tuple[tuple[str, Path], ...]


class FolderError(ValueError):
    """Папка не разрешена или её нет; текст — для озвучки."""


def _checked(label: str, path: Path) -> tuple[str, Path]:
    if not path.is_dir():
        raise FolderError(f"Папки «{label}» нет на диске.")
    return label, path


def _inside(folders: Folders, real: Path, asked: str) -> tuple[str, Path]:
    """Подпись «имя/подпапка» для настоящего пути `real` внутри разрешённой папки."""
    for name, root in folders:
        if real == root or real.is_relative_to(root):
            rel = real.relative_to(root).as_posix()
            return _checked(name if rel == "." else f"{name}/{rel}", real)
    raise FolderError(f"Папка «{asked}» не из разрешённых.")


def _by_name(folders: Folders, name: str) -> tuple[str, Path] | None:
    for known, root in folders:
        if known.casefold() == name.casefold():
            return known, root
    return None


def resolve_folder(folders: Folders, requested: str) -> tuple[str, Path]:
    """Папка задачи по имени из настроек, «имя/подпапка» или пути; пусто — первая.

    Возвращает (подпись для речи, настоящий путь). Ошибка — `FolderError` с текстом.
    """
    if not folders:
        raise FolderError(NO_FOLDERS)
    asked = requested.strip()
    if not asked:
        return _checked(*folders[0])
    named = _by_name(folders, asked)
    if named is not None:
        return _checked(*named)
    if asked.startswith(("/", "~")):
        return _inside(folders, Path(os.path.realpath(os.path.expanduser(asked))), asked)
    head, _, rest = asked.partition("/")
    named = _by_name(folders, head)
    if named is None or not rest:
        names = ", ".join(name for name, _ in folders)
        raise FolderError(f"Нет папки «{head or asked}». Есть: {names}.")
    return _inside(folders, Path(os.path.realpath(named[1] / rest)), asked)
