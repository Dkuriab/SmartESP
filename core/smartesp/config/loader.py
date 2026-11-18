"""Поиск папки данных и загрузка config.yaml.

В config.yaml хранятся только настройки, которые владелец поменял сам; всё
остальное берётся из значений по умолчанию в коде, поэтому новые возможности
приходят без правки файла. Полный список значений по умолчанию — рядом, в
config.defaults.yaml (только для справки, перезаписывается при каждом старте).
"""

import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import CONFIG_VERSION, Config
from .models import DEFAULT_SYSTEM_PROMPT as _CURRENT_PROMPT

HEADER = """# Настройки ядра SmartESP: здесь только то, что вы поменяли сами.
# Все значения по умолчанию — в config.defaults.yaml рядом (только для справки):
# скопируйте оттуда нужный ключ сюда и поменяйте. После правки перезапустите ядро.
"""
DEFAULTS_HEADER = """# Значения по умолчанию — ТОЛЬКО ДЛЯ СПРАВКИ, ядро перезаписывает этот файл при старте.
# Чтобы поменять настройку, перенесите ключ в config.yaml.
"""
# Пример колонки: только комментарии, загрузку не меняет.
DEVICES_EXAMPLE = """
# Колонки: ключ — MAC Wi-Fi из hello колонки (заглавными, через двоеточие),
# обязательно в кавычках: MAC из одних цифр без кавычек YAML прочтёт как число.
# devices:
#   "AA:BB:CC:DD:EE:FF":
#     name: Кухня
"""
# Системные промпты по умолчанию прежних версий: в старом файле они значат «не меняли».
_LEGACY_PROMPTS = (
    _CURRENT_PROMPT,
    _CURRENT_PROMPT + " Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]."
    " Во всех остальных случаях никаких меток не пиши.",
)


def data_dir() -> Path:
    """Папка данных: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


def load_config(path: Path) -> Config:
    """Читает настройки: изменения из config.yaml поверх значений по умолчанию.

    Нет файла — создаёт пустой (с подсказками). Файл прежнего формата (все
    настройки целиком, без version) один раз переводится: остаются только
    отличия от значений по умолчанию, старый файл сохраняется как config.yaml.bak.
    Файл версии 2 так же сохраняется в .bak и переписывается как версия 3 (tts без
    kind остаётся piper — прежнее умолчание).
    Рядом пишется config.defaults.yaml. Файл не читается, не разбирается как YAML
    или настройки неверные — ValueError с понятным сообщением и путём к файлу.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_defaults(path.with_name("config.defaults.yaml"))
    if not path.exists():
        _write_overrides(path, {})
        return Config()
    raw = _read(path)
    version = raw.get("version")
    if version is not None and (isinstance(version, bool) or version not in (2, CONFIG_VERSION)):
        raise ValueError(f"файл настроек от более новой версии ядра: {path} (version: {version!r})")
    if version != CONFIG_VERSION:
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
        raw = _migrate(raw) if version is None else _migrate_v2(raw)
        _write_overrides(path, raw)
    try:
        return Config.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"неверные настройки в {path}:\n{error}") from error


def _read(path: Path) -> dict[str, Any]:
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


def _migrate_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Версия 2 → 3: умолчанием tts был piper, поэтому tts без kind закрепляем как piper."""
    raw = {k: v for k, v in raw.items() if k != "version"}
    tts = raw.get("tts")
    if isinstance(tts, dict) and "kind" not in tts:
        raw["tts"] = {"kind": "piper", **tts}
    return raw


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Файл прежнего формата → только отличия от значений по умолчанию."""
    raw = dict(raw)
    if raw.get("stages") == []:
        del raw["stages"]  # прежнее умолчание «без обработчиков», а не выбор владельца
    if raw.get("tts") == {"kind": "piper", "voice": "ru_RU-irina-medium"}:
        del raw["tts"]  # прежнее умолчание-голос, а не выбор владельца
    if _is_legacy_executors(raw.get("executors")):
        del raw["executors"]
    return _prune(raw, Config().model_dump())


def _is_legacy_executors(value: object) -> bool:
    """Список исполнителей совпадает с умолчанием прежних версий (с любым прежним промптом)."""
    defaults = Config().model_dump()["executors"]
    if not isinstance(value, list) or len(value) != len(defaults):
        return False
    for item, default in zip(value, defaults, strict=True):
        if not isinstance(item, dict) or item.get("system_prompt") not in _LEGACY_PROMPTS:
            return False
        if {k: v for k, v in item.items() if k != "system_prompt"} != {
            k: v for k, v in default.items() if k != "system_prompt"
        }:
            return False
    return True


def _prune(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Убирает из raw значения, совпадающие с умолчаниями (вглубь по словарям)."""
    result: dict[str, Any] = {}
    for key, value in raw.items():
        default = defaults.get(key)
        if isinstance(value, dict) and isinstance(default, dict):
            nested = _prune(value, default)
            if nested:
                result[key] = nested
        elif key not in defaults or value != default:
            result[key] = value
    return result


def _write_overrides(path: Path, overrides: dict[str, Any]) -> None:
    """Пишет config.yaml атомарно (временный файл рядом и replace): версия формата и изменения владельца."""
    body = yaml.safe_dump({"version": CONFIG_VERSION, **overrides}, allow_unicode=True, sort_keys=False)
    example = "" if "devices" in overrides else DEVICES_EXAMPLE
    text = HEADER + body + example
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)  # атомарно: читатель видит старый файл целиком или новый целиком
    finally:
        temp.unlink(missing_ok=True)


def _write_defaults(path: Path) -> None:
    """Пишет config.defaults.yaml — все значения по умолчанию, для справки."""
    body = yaml.safe_dump(Config().model_dump(), allow_unicode=True, sort_keys=False)
    path.write_text(DEFAULTS_HEADER + body, encoding="utf-8")
