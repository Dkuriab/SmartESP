"""Настройки, которые коннектор объявляет сам: файл smartesp.json в папке его проекта.

Формат: `{"settings": [{"key", "title", "type", "hint"}], "note": "…", "example": "…",
"core_api": false}`, type —
text, path, list, secret или flag; note и example (необязательны) — пояснение для панели
коннектора и пример для config.yaml (например, почему настроек в приложении нет); core_api —
коннектору нужен API ядра (адрес и токен в окружении, как клиенту: SMARTESP_URL, SMARTESP_TOKEN).
Через API у коннектора можно менять только объявленные ключи env (см. api_patch.py).
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
SettingType = Literal["text", "path", "list", "secret", "flag", "pairs"]
# Главная граница — свой префикс коннектора (settable_key). Это — вторая линия: окружение,
# которое меняет, что и как запускается (sh -c — это bash на macOS, uv, node, perl, ruby, pip,
# git), куда идёт трафик (прокси, CA) или как читаются файлы: через API не меняется никогда.
_PROTECTED = re.compile(
    r"^(PATH|HOME|SHELL|ENV|IFS|TMPDIR|LANG|LC_.*|VIRTUAL_ENV|SHELLOPTS|BASHOPTS|PS4|BASH_.*"
    r"|PYTHON.*|DYLD_.*|LD_.*|UV_.*|PIP_.*|NODE_.*|PERL5.*|PERLLIB|RUBY.*|GIT_.*|XDG_.*"
    r"|SSL_.*|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|.*_PROXY|ANTHROPIC_.*|SMARTESP_.*)$",
    re.IGNORECASE,
)
_KEY_FORM = re.compile(r"^[A-Z][A-Z0-9_]*$")

# такие ключи скрыты и в GET /config; то же правило — api/redact.py (SECRET_KEY, MASKED),
# равенство проверяет тест: api не импортирует config
SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.IGNORECASE)
_warned: set[tuple[str, str]] = set()  # (id, ключ): о пропуске уже писали


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
        return self.type == "secret" or bool(SECRET_NAME.search(self.key))


class _Manifest(BaseModel):
    settings: list[ConnectorSetting] = Field(default_factory=list[ConnectorSetting])
    note: str = ""
    example: str = ""
    core_api: bool = False


def protected_key(key: str) -> bool:
    """True — ключ окружения нельзя менять через API ни при каком объявлении."""
    return bool(_PROTECTED.match(key))


def key_prefix(cid: str) -> str:
    """Свой префикс коннектора: id заглавными, не буквы и не цифры — «_», плюс «_».

    Например, mac_media → MAC_MEDIA_, my-conn → MY_CONN_.
    """
    return re.sub(r"[^A-Za-z0-9]", "_", cid).upper() + "_"


def settable_key(cid: str, key: str) -> bool:
    """Ключ можно объявить для API: заглавные [A-Z][A-Z0-9_]*, свой префикс, не под запретом."""
    return bool(_KEY_FORM.match(key)) and key.startswith(key_prefix(cid)) and not protected_key(key)


def project_dir(args: Sequence[str]) -> Path | None:
    """Папка проекта коннектора: значение после `--project` в args (уже с подставленным {repo})."""
    for flag, value in zip(args, args[1:], strict=False):
        if flag == "--project":
            return Path(value)
    return None


def _manifest(connector: ConnectorConfig) -> _Manifest:
    """smartesp.json проекта коннектора; нет файла или он неверный — пустой."""
    folder = project_dir(connector.expanded().args)
    if folder is None:
        return _Manifest()
    path = folder / MANIFEST_NAME
    try:
        return _Manifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return _Manifest()
    except (OSError, ValidationError) as error:
        _log.warning("Коннектор %s: не читается %s, настроек нет: %s", connector.id, path, error)
        return _Manifest()


def manifest_note(connector: ConnectorConfig) -> dict[str, str]:
    """Пояснение и пример из smartesp.json: {note, example}; нет — пустые строки."""
    manifest = _manifest(connector)
    return {"note": manifest.note, "example": manifest.example}


def wants_core_api(connector: ConnectorConfig) -> bool:
    """Коннектор заявил в smartesp.json `"core_api": true`: ему нужны адрес и токен API ядра."""
    return _manifest(connector).core_api


def declared_settings(connector: ConnectorConfig) -> list[ConnectorSetting]:
    """Настройки из smartesp.json проекта коннектора, только с годными ключами (settable_key).

    Негодный ключ пропускается (в интерфейс не попадает) с предупреждением — одним на ключ.
    """
    allowed: list[ConnectorSetting] = []
    for setting in _manifest(connector).settings:
        if settable_key(connector.id, setting.key):
            allowed.append(setting)
        elif (connector.id, setting.key) not in _warned:
            _warned.add((connector.id, setting.key))
            _log.warning(
                "Коннектор %s: ключ %s в %s пропущен — нужен свой префикс %s и не системный ключ",
                connector.id,
                setting.key,
                MANIFEST_NAME,
                key_prefix(connector.id),
            )
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
