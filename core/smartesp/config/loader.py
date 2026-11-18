"""Поиск папки данных и загрузка config.yaml."""

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Config

# Пример в конце файла по умолчанию: только комментарии, загрузку не меняет.
DEVICES_EXAMPLE = """
# Колонки: ключ — MAC Wi-Fi из hello колонки (заглавными, через двоеточие),
# обязательно в кавычках: MAC из одних цифр без кавычек YAML прочтёт как число.
# devices:
#   "AA:BB:CC:DD:EE:FF":
#     name: Кухня
"""


def data_dir() -> Path:
    """Папка данных: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


def load_config(path: Path) -> Config:
    """Читает настройки из YAML.

    Нет файла — записывает настройки по умолчанию (с закомментированным примером
    колонки) и возвращает их. Файл не читается, не разбирается как YAML или
    настройки в нём неверные — ValueError с понятным сообщением и путём к файлу.
    """
    if not path.exists():
        config = Config()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(config.model_dump(), allow_unicode=True, sort_keys=False)
        path.write_text(text + DEVICES_EXAMPLE, encoding="utf-8")
        return config
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"не удалось прочитать файл настроек {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"ошибка YAML в файле настроек {path}:\n{error}") from error
    try:
        return Config.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"неверные настройки в {path}:\n{error}") from error
