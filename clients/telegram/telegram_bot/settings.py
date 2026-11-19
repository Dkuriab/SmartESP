"""Настройки бота: файл TOML вне git (шаблон — `settings.example.toml`)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORE_URL = "http://127.0.0.1:8765"


class SettingsError(Exception):
    """Файл настроек отсутствует или заполнен неверно; текст — что поправить."""


@dataclass(frozen=True)
class Settings:
    """Настройки бота.

    `users` — кто допущен: `user_id` Telegram → имя человека для ядра.
    """

    bot_token: str
    core_url: str
    core_token: str
    users: dict[int, str]


def load_settings(path: Path) -> Settings:
    """Читает и проверяет файл настроек; ошибка — `SettingsError` с подсказкой."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(
            f"Нет файла настроек {path}: скопируйте settings.example.toml в settings.toml и заполните"
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"Файл {path} — неверный TOML: {error}") from None
    telegram = _table(raw, "telegram")
    core = _table(raw, "core")
    return Settings(
        bot_token=_required_text(telegram, "telegram.bot_token", "bot_token"),
        core_url=_core_url(core),
        core_token=_required_text(core, "core.token", "token"),
        users=_users(_table(raw, "users")),
    )


def _table(raw: dict[str, object], name: str) -> dict[str, object]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise SettingsError(f"[{name}] должен быть разделом")
    return value  # type: ignore[return-value]


def _required_text(table: dict[str, object], label: str, key: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(f"Не заполнен {label}")
    return value.strip()


def _core_url(core: dict[str, object]) -> str:
    value = core.get("url", DEFAULT_CORE_URL)
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise SettingsError("core.url должен начинаться с http:// или https://")
    return value.rstrip("/")


def _users(table: dict[str, object]) -> dict[int, str]:
    if not table:
        raise SettingsError('В [users] никого нет: впишите свой user_id = "имя"')
    users: dict[int, str] = {}
    for key, name in table.items():
        if not key.isdigit():
            raise SettingsError(f"В [users] ключ «{key}» — не user_id (нужны цифры)")
        if not isinstance(name, str) or not name.strip():
            raise SettingsError(f"В [users] у {key} должно быть имя-строка")
        users[int(key)] = name.strip()
    return users
