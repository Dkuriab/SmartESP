"""Настройки бота: окружение от ядра или файл TOML вне git (шаблон — `settings.example.toml`).

Когда бота запускает ядро (вкладка коннекторов приложения: «Telegram-бот»), оно передаёт адрес и
токен API (SMARTESP_URL, SMARTESP_TOKEN) и настройки из приложения: TELEGRAM_BOT_TOKEN и
TELEGRAM_USERS («id=имя;id=имя»). Заполненное в окружении важнее файла; пустое — берётся из файла.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORE_URL = "http://127.0.0.1:8765"


class SettingsError(Exception):
    """Файл настроек отсутствует или заполнен неверно; текст — что поправить."""


@dataclass(frozen=True)
class Settings:
    """Настройки бота.

    `users` — кто допущен: `user_id` Telegram → имя человека для ядра; `managed` — бота запустило
    ядро (тогда незнакомые предлагаются приложению «Добавить», а пустой список людей — не ошибка).
    """

    bot_token: str
    core_url: str
    core_token: str
    users: dict[int, str]
    managed: bool = False


def _read(path: Path, managed: bool) -> dict[str, object]:
    """Содержимое файла настроек; нет файла у бота от ядра — пусто (всё в окружении)."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if managed:
            return {}
        raise SettingsError(
            f"Нет файла настроек {path}: скопируйте settings.example.toml в settings.toml и заполните"
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"Файл {path} — неверный TOML: {error}") from None


def load_settings(path: Path, env: Mapping[str, str] | None = None) -> Settings:
    """Читает и проверяет настройки (окружение поверх файла); ошибка — `SettingsError` с подсказкой."""
    env = os.environ if env is None else env
    managed = bool(env.get("SMARTESP_URL", "").strip())
    raw = _read(path, managed)
    telegram, core = _table(raw, "telegram"), _table(raw, "core")
    telegram = {
        **telegram,
        "bot_token": env.get("TELEGRAM_BOT_TOKEN", "").strip() or telegram.get("bot_token", ""),
    }
    core = {**core, "url": env.get("SMARTESP_URL", "").strip() or core.get("url", DEFAULT_CORE_URL)}
    core = {**core, "token": env.get("SMARTESP_TOKEN", "").strip() or core.get("token", "")}
    listed = env.get("TELEGRAM_USERS", "").strip()
    users = _pairs(listed) if listed else _users(_table(raw, "users"), allow_empty=managed)
    hint = "токен бота — в приложении (Telegram-бот → настройки)" if managed else "telegram.bot_token"
    return Settings(
        bot_token=_required_text(telegram, hint, "bot_token"),
        core_url=_core_url(core),
        core_token=_required_text(core, "core.token", "token"),
        users=users,
        managed=managed,
    )


def _pairs(text: str) -> dict[int, str]:
    """«123=Аня;456=Борис» из TELEGRAM_USERS → {123: "Аня", 456: "Борис"}."""
    users: dict[int, str] = {}
    for item in text.split(";"):
        key, _, name = (part.strip() for part in item.partition("="))
        if not key:
            continue
        if not key.isdigit() or not name:
            raise SettingsError(f"TELEGRAM_USERS: запись «{item.strip()}» — нужно «user_id=имя»")
        users[int(key)] = name
    return users


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


def _users(table: dict[str, object], *, allow_empty: bool = False) -> dict[int, str]:
    if not table and allow_empty:
        return {}
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
