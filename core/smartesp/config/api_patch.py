"""Правка connectors через API: что можно менять и проверка значений настроек.

Можно: `enabled` у уже известного id и `env` — только ключи, объявленные самим коннектором
в smartesp.json (manifest.py). Всё прочее (команда, аргументы, имя, новый коннектор,
remove, сброс списка, необъявленный ключ) — только руками в config.yaml: иначе токен API
стал бы запуском любой команды на Mac.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from .connectors import ConnectorConfig
from .manifest import MASK, ConnectorSetting, declared_settings, settable_key

API_FIELDS = frozenset({"id", "enabled", "env"})
API_ONLY_TEXT = "Команду коннектора и необъявленные настройки меняют только в config.yaml"
MAX_VALUE = 500  # символов в значении настройки
# управляющие (C0/C1, в том числе NUL, \t, \n, \r, NEL) и разделители строк: YAML меняет их при чтении
_BAD_CATEGORIES = ("Cc", "Zl", "Zp")


def check_api_entries(entries: object, connectors: Sequence[ConnectorConfig]) -> list[object]:
    """Проверяет правку connectors из API; возвращает её же без неизменённых секретов.

    connectors — действующие коннекторы. Секрет со значением MASK (так его показывает API) —
    «не менять»: из правки убирается. Нарушение — ValueError с понятным текстом.
    """
    if not isinstance(entries, list):
        raise ValueError(API_ONLY_TEXT)
    known = {c.id: c for c in connectors}
    result: list[object] = []
    for item in cast(list[object], entries):
        if not isinstance(item, dict):
            raise ValueError(API_ONLY_TEXT)
        entry = cast(dict[str, object], item)
        cid = entry.get("id")
        if not set(entry) <= API_FIELDS or not isinstance(cid, str) or cid not in known:
            raise ValueError(API_ONLY_TEXT)
        if "env" in entry:
            declared = {s.key: s for s in declared_settings(known[cid])}
            entry = {**entry, "env": _checked_env(cid, entry["env"], declared)}
        result.append(entry)
    return result


def _checked_env(cid: str, env: object, declared: Mapping[str, ConnectorSetting]) -> dict[str, str | None]:
    """Значения объявленных ключей (None — сбросить к умолчанию); неизменённые секреты убраны."""
    if not isinstance(env, dict):
        raise ValueError(API_ONLY_TEXT)
    result: dict[str, str | None] = {}
    for key, value in cast(dict[object, object], env).items():
        setting = declared.get(key) if isinstance(key, str) else None
        if setting is None or not settable_key(cid, setting.key):
            raise ValueError(f"Настройку {key} коннектора {cid} меняют только в config.yaml")
        if value is None:
            result[setting.key] = None
            continue
        text = check_value(setting, value)
        if setting.secret and text == MASK:
            continue
        result[setting.key] = text
    return result


def check_value(setting: ConnectorSetting, value: object) -> str:
    """Проверенное значение настройки; неверное — ValueError с ключом в тексте."""
    key = setting.key
    if not isinstance(value, str):
        raise ValueError(f"{key}: значение должно быть строкой")
    if len(value) > MAX_VALUE:
        raise ValueError(f"{key}: не длиннее {MAX_VALUE} символов")
    if any(unicodedata.category(c) in _BAD_CATEGORIES for c in value):
        raise ValueError(f"{key}: значение в одну строку")
    if setting.type == "flag" and value not in ("", "1"):
        raise ValueError(f"{key}: флаг — «1» или пусто")
    if setting.type == "path" and value and not _absolute(value):
        raise ValueError(f"{key}: путь должен начинаться с / или ~/")
    if setting.type == "list":
        _check_folders(key, value)
    return value


def _absolute(path: str) -> bool:
    """Путь абсолютный или от домашней папки (~, ~/…)."""
    return path.startswith("/") or path == "~" or path.startswith("~/")


def _check_folders(key: str, value: str) -> None:
    """`имя=путь;имя=путь`: имена без повторов, пути — существующие папки (/ или ~/)."""
    names: set[str] = set()
    for item in value.split(";"):
        if not item.strip():
            continue
        name, sep, path = (part.strip() for part in item.partition("="))
        if not sep or not name or not path:
            raise ValueError(f"{key}: запись «{item.strip()}» — нужно «имя=путь»")
        if name.casefold() in names:
            raise ValueError(f"{key}: имя «{name}» повторяется")
        names.add(name.casefold())
        if not _absolute(path):
            raise ValueError(f"{key}: путь «{path}» должен начинаться с / или ~/")
        if not Path(path).expanduser().is_dir():
            raise ValueError(f"{key}: папки «{path}» нет")
