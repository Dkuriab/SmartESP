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

from ._files import prune, read_yaml, write_overrides
from .models import CONFIG_VERSION, DEFAULT_SYSTEM_PROMPT, Config

DEFAULTS_HEADER = """# Значения по умолчанию — ТОЛЬКО ДЛЯ СПРАВКИ, ядро перезаписывает этот файл при старте.
# Чтобы поменять настройку, перенесите ключ в config.yaml.
"""
# Системные промпты по умолчанию прежних версий: в старом файле они значат «не меняли».
_OLD_PROMPT = (
    "Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен."
)
_KUZYA_PROMPT = (
    "Тебя зовут Кузя. Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен."
)
_LEGACY_PROMPTS = (
    DEFAULT_SYSTEM_PROMPT,
    _KUZYA_PROMPT,
    _OLD_PROMPT,
    _OLD_PROMPT + " Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]."
    " Во всех остальных случаях никаких меток не пиши.",
)


def data_dir() -> Path:
    """Папка данных: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


def load_config(path: Path) -> Config:
    """Читает настройки (см. load_with_overrides)."""
    return load_with_overrides(path)[0]


def load_with_overrides(path: Path) -> tuple[Config, dict[str, Any]]:
    """Читает настройки: изменения из config.yaml поверх значений по умолчанию.

    Нет файла — создаёт пустой (с подсказками). Файл прежнего формата (все
    настройки целиком, без version) один раз переводится: остаются только
    отличия от значений по умолчанию, старый файл сохраняется как config.yaml.bak.
    Файл версии 2 или 3 так же сохраняется в .bak и переписывается как версия 4 (tts без
    kind остаётся piper — прежнее умолчание; к сохранённым stages добавляется clock).
    Рядом пишется config.defaults.yaml. Файл не читается, не разбирается как YAML
    или настройки неверные — ValueError с понятным сообщением и путём к файлу.
    Возвращает настройки и изменения владельца (содержимое файла без version).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_defaults(path.with_name("config.defaults.yaml"))
    if not path.exists():
        write_overrides(path, {})
        return Config(), {}
    raw = read_yaml(path)
    version = raw.get("version")
    if version is not None and (isinstance(version, bool) or version not in (2, 3, CONFIG_VERSION)):
        raise ValueError(f"файл настроек от более новой версии ядра: {path} (version: {version!r})")
    if version != CONFIG_VERSION:
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
        if version is None:
            raw = _migrate(raw)
        if version in (None, 2):
            raw = _migrate_v2(raw)
        raw = _migrate_v3(raw)  # версии идут цепочкой: 2 → 3 → 4
        write_overrides(path, raw)
    try:
        config = Config.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"неверные настройки в {path}:\n{error}") from error
    return config, {k: v for k, v in raw.items() if k != "version"}


def _migrate_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Версия 3 → 4: в сохранённый список stages добавляем clock (один раз, по версии).

    После перехода владелец, убравший clock, этот выбор сохраняет. Список, ставший
    равным умолчанию, из файла убирается.
    """
    raw = {k: v for k, v in raw.items() if k != "version"}
    stages = raw.get("stages")
    if isinstance(stages, list) and not any(isinstance(s, dict) and s.get("kind") == "clock" for s in stages):
        raw["stages"] = [*stages, {"kind": "clock"}]
        raw = prune(raw, Config().model_dump())
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
    return prune(raw, Config().model_dump())


def _is_legacy_executors(value: object) -> bool:
    """Список исполнителей совпадает с умолчанием прежних версий (с любым прежним промптом)."""
    # прежнее умолчание — один диспетчер без связей (сеть из двух исполнителей появилась позже)
    legacy = Config().executors[0].model_dump(exclude={"delegates", "description"})
    defaults = [legacy]
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


def _write_defaults(path: Path) -> None:
    """Пишет config.defaults.yaml — все значения по умолчанию, для справки."""
    body = yaml.safe_dump(Config().model_dump(), allow_unicode=True, sort_keys=False)
    path.write_text(DEFAULTS_HEADER + body, encoding="utf-8")
