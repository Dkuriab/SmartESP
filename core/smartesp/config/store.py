"""Хранилище настроек для API: чтение, слияние частичных правок, атомарная запись."""

import copy
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from ._files import prune, write_overrides
from .loader import load_with_overrides
from .models import Config


class ConfigFile:
    """Файл config.yaml: текущие настройки и изменения владельца поверх умолчаний."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._config: Config | None = None
        self._overrides: dict[str, Any] = {}

    def load(self) -> Config:
        """Читает файл (как load_config, с переводом старого формата) и запоминает."""
        config, self._overrides = load_with_overrides(self._path)
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
        if not isinstance(patch, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("правка настроек должна быть словарём")
        if "version" in patch:
            raise ValueError("ключ version менять нельзя")
        merged = _merge(self._overrides, patch)
        _check_keys(Config, merged, "")
        try:
            return Config.model_validate(merged)
        except ValidationError as error:
            raise ValueError(f"неверные настройки:\n{error}") from error

    def save(self, config: Config) -> None:
        """Пишет в файл только отличия от умолчаний (атомарно) и запоминает их."""
        overrides = prune(config.model_dump(mode="json"), Config().model_dump(mode="json"))
        write_overrides(self._path, overrides)
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


def _models_in(annotation: object) -> list[type[BaseModel]]:
    """Модели, вложенные в тип поля: сама модель, элементы списка, значения словаря."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [m for arg in get_args(annotation) for m in _models_in(arg)]


def _check_keys(model: type[BaseModel], data: dict[str, Any], prefix: str) -> None:
    """Отвергает неизвестные ключи вглубь; ключи-идентификаторы (devices) свободны."""
    for key, value in data.items():
        field = model.model_fields.get(key)
        if field is None:
            raise ValueError(f"неизвестный ключ настроек: {prefix}{key}")
        nested = _models_in(field.annotation)
        if len(nested) == 1:
            _check_value(field.annotation, nested[0], value, f"{prefix}{key}")


def _check_value(annotation: object, sub: type[BaseModel], value: object, name: str) -> None:
    """Проверяет значение поля: модель, словарь моделей по идентификаторам или список моделей."""
    origin = get_origin(annotation)
    items: list[tuple[str, object]] = []
    if origin is dict and isinstance(value, dict):
        items = [(f"{name}.{k}", v) for k, v in value.items()]  # pyright: ignore[reportUnknownVariableType]
    elif origin is list and isinstance(value, list):
        items = [(f"{name}[{i}]", v) for i, v in enumerate(value)]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    elif origin is None:
        items = [(name, value)]
    for item_name, item in items:
        if isinstance(item, dict):
            _check_keys(sub, item, item_name + ".")  # pyright: ignore[reportUnknownArgumentType]
