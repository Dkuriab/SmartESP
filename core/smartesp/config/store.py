"""Хранилище настроек для API: чтение, слияние частичных правок, атомарная запись."""

import copy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .loader import _prune, _read, _write_overrides, load_config  # pyright: ignore[reportPrivateUsage]
from .models import Config


class ConfigFile:
    """Файл config.yaml: текущие настройки и изменения владельца поверх умолчаний."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._config: Config | None = None
        self._overrides: dict[str, Any] = {}

    def load(self) -> Config:
        """Читает файл (как load_config, с переводом старого формата) и запоминает."""
        config = load_config(self._path)
        raw = _read(self._path)
        raw.pop("version", None)
        self._overrides = raw
        self._config = config
        return config

    @property
    def config(self) -> Config:
        """Текущие настройки (после load или save)."""
        if self._config is None:
            raise RuntimeError("настройки ещё не загружены: вызовите load()")
        return self._config

    def effective(self) -> dict[str, Any]:
        """Настройки целиком, в форме config.yaml."""
        return self.config.model_dump(mode="json")

    def overridden(self) -> list[str]:
        """Ключи через точку, которые владелец поменял (списки — один ключ)."""
        return _dotted(self._overrides, "")

    def merge(self, patch: dict[str, Any]) -> Config:
        """Сливает правку с изменениями владельца; ничего не пишет.

        Словари сливаются вглубь, списки заменяются целиком, null сбрасывает ключ
        к умолчанию. Неверный результат — ValueError с понятным текстом.
        """
        merged = _merge(self._overrides, patch)
        try:
            return Config.model_validate(merged)
        except ValidationError as error:
            raise ValueError(f"неверные настройки:\n{error}") from error

    def save(self, config: Config) -> None:
        """Пишет в файл только отличия от умолчаний (атомарно) и запоминает их."""
        overrides = _prune(config.model_dump(mode="json"), Config().model_dump(mode="json"))
        _write_overrides(self._path, overrides)
        self._overrides = overrides
        self._config = config

    @staticmethod
    def section(config: Config, name: str) -> object:
        """Значение одного раздела верхнего уровня — для сравнения до и после правки."""
        return config.model_dump(mode="json")[name]


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Вглубь по словарям; None убирает ключ; остальное (в том числе список) заменяет."""
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            current = result.get(key)
            result[key] = _merge(current if isinstance(current, dict) else {}, value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            result[key] = copy.deepcopy(value)
    return result


def _dotted(tree: dict[str, Any], prefix: str) -> list[str]:
    """Листья словаря как ключи через точку."""
    keys: list[str] = []
    for key, value in tree.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            keys.extend(_dotted(value, name + "."))  # pyright: ignore[reportUnknownArgumentType]
        else:
            keys.append(name)
    return keys
