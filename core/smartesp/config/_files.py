"""Общие для загрузчика и хранилища функции работы с config.yaml (внутренний модуль)."""

import os
from pathlib import Path
from typing import Any

import yaml

from .connectors import connector_overrides, overlay_connectors
from .models import CONFIG_VERSION, Config

HEADER = """# Настройки ядра SmartESP: здесь только то, что вы поменяли сами.
# Все значения по умолчанию — в config.defaults.yaml рядом (только для справки):
# скопируйте оттуда нужный ключ сюда и поменяйте. После правки перезапустите ядро.
"""
# Пример колонки: только комментарии, загрузку не меняет.
DEVICES_EXAMPLE = """
# Колонки: ключ — MAC Wi-Fi из hello колонки (заглавными, через двоеточие),
# обязательно в кавычках: MAC из одних цифр без кавычек YAML прочтёт как число.
# devices:
#   "AA:BB:CC:DD:EE:FF":
#     name: Кухня
"""


def read_yaml(path: Path) -> dict[str, Any]:
    """Содержимое YAML-файла как словарь (пустой файл — пустой словарь)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"не удалось прочитать файл настроек {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"ошибка YAML в файле настроек {path}:\n{error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"неверные настройки в {path}: ожидался словарь ключей")
    return raw


def prune(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Убирает из raw значения, совпадающие с умолчаниями (вглубь по словарям)."""
    result: dict[str, Any] = {}
    for key, value in raw.items():
        default = defaults.get(key)
        if isinstance(value, dict) and isinstance(default, dict):
            nested = prune(value, default)
            if nested:
                result[key] = nested
        elif key not in defaults or value != default:
            result[key] = value
    return result


def owner_changes(raw: dict[str, Any], *, effective: bool) -> dict[str, Any]:
    """Только отличия от умолчаний: как prune, но connectors — по id, лишь изменённые поля.

    effective — raw содержит настройки целиком (иначе это записи владельца из файла).
    """
    connectors = raw.get("connectors")
    result = prune({k: v for k, v in raw.items() if k != "connectors"}, Config().model_dump(mode="json"))
    if connectors is not None:
        changed = connector_overrides(connectors if effective else overlay_connectors(connectors))
        if changed:
            result["connectors"] = changed
    return result


def write_overrides(path: Path, overrides: dict[str, Any]) -> None:
    """Пишет config.yaml атомарно (временный файл рядом и replace): версия формата и изменения владельца."""
    data = {"version": CONFIG_VERSION, **{k: v for k, v in overrides.items() if k != "version"}}
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    example = "" if "devices" in overrides else DEVICES_EXAMPLE
    text = HEADER + body + example
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)  # атомарно: читатель видит старый файл целиком или новый целиком
    finally:
        temp.unlink(missing_ok=True)
