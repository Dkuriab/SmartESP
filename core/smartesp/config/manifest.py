"""Настройки, которые коннектор объявляет сам: файл smartesp.json в папке его проекта.

Формат: `{"settings": [{"key", "title", "type", "hint"}]}`, type — text, path, list, secret
или flag. Через API у коннектора можно менять только объявленные ключи env (см. api_patch.py).
Файл только читается; ключи окружения, опасные для запуска (PATH, PYTHON*, DYLD_* …),
не объявляются никогда, что бы файл ни говорил.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from .connectors import ConnectorConfig

_log = logging.getLogger(__name__)

MANIFEST_NAME = "smartesp.json"
MASK = "•••"  # значение секрета в ответах API; оно же назад — «не менять»
SettingType = Literal["text", "path", "list", "secret", "flag"]
# окружение, которое меняет, что и как запускается: через API не меняется никогда
_PROTECTED = re.compile(
    r"^(PATH|HOME|SHELL|ENV|BASH_ENV|IFS|VIRTUAL_ENV|PYTHON.*|DYLD_.*|LD_.*|UV_.*|SMARTESP_.*)$",
    re.IGNORECASE,
)

# такие ключи скрыты и в GET /config (api/redact.py), даже если объявлены как text
_SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.IGNORECASE)


class ConnectorSetting(BaseModel):
    """Объявленная настройка: ключ env, подпись и подсказка для людей, тип поля."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    title: str
    type: SettingType = "text"
    hint: str = ""

    @property
    def secret(self) -> bool:
        """Значение скрыто в ответах API: тип secret или имя ключа как у секрета."""
        return self.type == "secret" or bool(_SECRET_NAME.search(self.key))


class _Manifest(BaseModel):
    settings: list[ConnectorSetting] = Field(default_factory=list[ConnectorSetting])


def protected_key(key: str) -> bool:
    """True — ключ окружения нельзя менять через API ни при каком объявлении."""
    return bool(_PROTECTED.match(key))


def project_dir(args: Sequence[str]) -> Path | None:
    """Папка проекта коннектора: значение после `--project` в args (уже с подставленным {repo})."""
    for flag, value in zip(args, args[1:], strict=False):
        if flag == "--project":
            return Path(value)
    return None


def declared_settings(connector: ConnectorConfig) -> list[ConnectorSetting]:
    """Настройки из smartesp.json проекта коннектора; нет файла или он неверный — пусто."""
    folder = project_dir(connector.expanded().args)
    if folder is None:
        return []
    path = folder / MANIFEST_NAME
    try:
        manifest = _Manifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return []
    except (OSError, ValidationError) as error:
        _log.warning("Коннектор %s: не читается %s, настроек нет: %s", connector.id, path, error)
        return []
    allowed = [s for s in manifest.settings if not protected_key(s.key)]
    if len(allowed) != len(manifest.settings):
        _log.warning("Коннектор %s: ключи PATH, PYTHON*, DYLD_* и т. п. в %s пропущены", connector.id, path)
    return allowed


def settings_view(connector: ConnectorConfig) -> list[dict[str, str]]:
    """Объявленные настройки с текущими значениями env; непустой секрет — MASK."""
    result: list[dict[str, str]] = []
    for setting in declared_settings(connector):
        value = connector.env.get(setting.key, "")
        if setting.secret and value:
            value = MASK
        result.append({**setting.model_dump(), "value": value})
    return result
