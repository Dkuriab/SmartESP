"""Поиск папки данных и загрузка config.yaml."""

import os
from pathlib import Path

import yaml

from .models import Config


def data_dir() -> Path:
    """Папка данных: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


def load_config(path: Path) -> Config:
    """Читает настройки из YAML.

    Нет файла — записывает настройки по умолчанию и возвращает их.
    Неверные настройки дают ValueError.
    """
    if not path.exists():
        config = Config()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(config.model_dump(), allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return config
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config.model_validate(raw)
