"""Хранилище настроек для API: чтение, слияние частичных правок, атомарная запись."""

import copy
import logging
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from ._files import prune, write_overrides
from .loader import load_with_overrides
from .models import Config

_log = logging.getLogger(__name__)


class ConfigFile:
    """Файл config.yaml: текущие настройки и изменения владельца поверх умолчаний."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._config: Config | None = None
        self._overrides: dict[str, Any] = {}
        self._unknown: list[str] = []  # неизвестные ключи из файла, через точку

    def load(self) -> Config:
        """Читает файл (как load_config, с переводом старого формата) и запоминает.

        Неизвестные ключи в файле (опечатки, ключи будущих версий) не мешают: ядро
        их не использует, пишет предупреждение, не показывает в overridden(), а при
        следующей записи (save) они из файла пропадают.
        """
        config, self._overrides = load_with_overrides(self._path)
        self._config = config
        self._unknown = _unknown_keys(Config, self._overrides, "")
        if self._unknown:
            _log.warning("В %s неизвестные ключи, не используются: %s", self._path, ", ".join(self._unknown))
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
        """Ключи через точку, которые владелец поменял (списки — один ключ); неизвестные — нет."""
        return [key for key in _dotted(self._overrides, "") if not _under(key, self._unknown)]

    def merge(self, patch: dict[str, Any]) -> Config:
        """Сливает правку с изменениями владельца; ничего не пишет.

        Словари сливаются вглубь, списки заменяются целиком, null сбрасывает ключ
        к умолчанию. Неизвестный ключ в правке или неверный результат — ValueError
        с понятным текстом; неизвестные ключи, уже лежащие в файле, правке не мешают.
        """
        if not isinstance(patch, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("правка настроек должна быть словарём")
        if "version" in patch:
            raise ValueError("ключ version менять нельзя")
        unknown = _unknown_keys(Config, patch, "")
        if unknown:
            raise ValueError(f"неизвестный ключ настроек: {unknown[0]}")
        merged = _merge(self._overrides, patch)
        try:
            return Config.model_validate(merged)
        except ValidationError as error:
            raise ValueError(f"неверные настройки:\n{error}") from error

    def save(self, config: Config) -> None:
        """Пишет в файл только отличия от умолчаний (атомарно) и запоминает их."""
        overrides = prune(config.model_dump(mode="json"), Config().model_dump(mode="json"))
        write_overrides(self._path, overrides)
        self._overrides = overrides
        self._unknown = []
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


def _under(key: str, names: list[str]) -> bool:
    """Ключ key — один из names или лежит внутри одного из них."""
    return any(key == name or key.startswith(name + ".") for name in names)


def _unknown_keys(model: type[BaseModel], data: dict[str, Any], prefix: str) -> list[str]:
    """Неизвестные ключи вглубь, через точку; ключи-идентификаторы (devices) свободны."""
    unknown: list[str] = []
    for key, value in data.items():
        field = model.model_fields.get(key)
        if field is None:
            unknown.append(f"{prefix}{key}")
            continue
        nested = _models_in(field.annotation)
        if len(nested) == 1:
            unknown.extend(_unknown_in_value(field.annotation, nested[0], value, f"{prefix}{key}"))
    return unknown


def _unknown_in_value(annotation: object, sub: type[BaseModel], value: object, name: str) -> list[str]:
    """Неизвестные ключи значения поля: модель, словарь моделей по идентификаторам или список моделей."""
    origin = get_origin(annotation)
    items: list[tuple[str, object]] = []
    if origin is dict and isinstance(value, dict):
        items = [(f"{name}.{k}", v) for k, v in value.items()]  # pyright: ignore[reportUnknownVariableType]
    elif origin is list and isinstance(value, list):
        items = [(f"{name}[{i}]", v) for i, v in enumerate(value)]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    elif origin is None:
        items = [(name, value)]
    unknown: list[str] = []
    for item_name, item in items:
        if isinstance(item, dict):
            unknown.extend(_unknown_keys(sub, item, item_name + "."))  # pyright: ignore[reportUnknownArgumentType]
    return unknown
