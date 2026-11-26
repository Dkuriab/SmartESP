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
from .models import LMSTUDIO_URL

API_FIELDS = frozenset({"id", "enabled", "env"})
API_ONLY_TEXT = "Команду коннектора и необъявленные настройки меняют только в config.yaml"
MAX_VALUE = 500  # символов в значении настройки
# управляющие (C0/C1, в том числе NUL, \t, \n, \r, NEL) и разделители строк: YAML меняет их при чтении
_BAD_CATEGORIES = ("Cc", "Zl", "Zp")


CLOUD_API_FIELDS = frozenset({"api_key"})
CLOUD_ONLY_TEXT = "Адрес и имя облачного сервиса меняют только в config.yaml; через API — только ключ"
LMSTUDIO_API_FIELDS = frozenset({"base_url", "api_key"})
LMSTUDIO_ONLY_TEXT = "В настройках LM Studio через API меняются только адрес (base_url) и ключ (api_key)"


def _one_line(value: str) -> bool:
    """Строка в одну строку и не длиннее MAX_VALUE."""
    return len(value) <= MAX_VALUE and not any(unicodedata.category(c) in _BAD_CATEGORIES for c in value)


def _checked_key(section: dict[str, object]) -> dict[str, object]:
    """{api_key} из правки раздела; нет ключа или «•••» (не менять) — пусто; неверный — ValueError."""
    key = section.get("api_key")
    if key is None or key == MASK:
        return {}
    if not isinstance(key, str) or not _one_line(key):
        raise ValueError(f"api_key: строка в одну строку, не длиннее {MAX_VALUE} символов")
    return {"api_key": key.strip()}


def check_cloud_patch(cloud: object) -> dict[str, object]:
    """Правка cloud из API: только api_key (строка в одну строку); «•••» — не менять, убирается."""
    if not isinstance(cloud, dict) or not set(cast(dict[str, object], cloud)) <= CLOUD_API_FIELDS:
        raise ValueError(CLOUD_ONLY_TEXT)
    return _checked_key(cast(dict[str, object], cloud))


def _checked_url(url: object) -> str | None:
    """Адрес сервера из правки: http(s)://… в одну строку; None — сброс к умолчанию."""
    if url is None:
        return None
    if not isinstance(url, str) or not _one_line(url) or not url.strip().startswith(("http://", "https://")):
        raise ValueError("base_url: адрес сервера вида http://localhost:1234")
    if len(url.strip().split("://", 1)[1].strip("/")) == 0:
        raise ValueError("base_url: в адресе нет сервера")
    return url.strip()


def check_lmstudio_patch(lmstudio: object, base_url: str, has_key: bool) -> dict[str, object]:
    """Правка lmstudio из API: base_url и api_key; «•••» в ключе — не менять.

    base_url, has_key — текущие адрес и есть ли ключ. Смена адреса без нового ключа в той же правке
    сбрасывает ключ: токен API не может увести ключ на чужой сервер.
    """
    if not isinstance(lmstudio, dict) or not set(cast(dict[str, object], lmstudio)) <= LMSTUDIO_API_FIELDS:
        raise ValueError(LMSTUDIO_ONLY_TEXT)
    section = cast(dict[str, object], lmstudio)
    result = _checked_key(section)
    if "base_url" in section:
        url = _checked_url(section["base_url"])
        result["base_url"] = url
        moved = (url or LMSTUDIO_URL).rstrip("/") != base_url.rstrip("/")
        if moved and has_key and "api_key" not in result:
            result["api_key"] = ""
    return result


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
    if setting.type == "pairs":
        _check_pairs(key, value)
    return value


def _check_pairs(key: str, value: str) -> None:
    """`ключ=значение;…` (например «123456789=Аня»): ключи без повторов, обе части непустые."""
    keys: set[str] = set()
    for item in value.split(";"):
        if not item.strip():
            continue
        name, sep, text = (part.strip() for part in item.partition("="))
        if not sep or not name or not text:
            raise ValueError(f"{key}: запись «{item.strip()}» — нужно «ключ=значение»")
        if name in keys:
            raise ValueError(f"{key}: «{name}» повторяется")
        keys.add(name)


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
