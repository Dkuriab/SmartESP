"""Сокрытие: токен из `?token=…` в журнале, секреты окружения коннекторов в GET /config."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence, Set
from typing import Any, cast

_TOKEN = re.compile(r"token=[^&\s\"']+")
HIDDEN = "token=***"


def hide_token(text: str) -> str:
    """Заменяет `token=<значение>` на `token=***` в готовом тексте (например, с traceback)."""
    return _TOKEN.sub(HIDDEN, text) if "token=" in text else text


class HideToken(logging.Filter):
    """Заменяет `token=<значение>` на `token=***` в итоговом тексте записи.

    Ставится на обработчики журнала (консоль, файл): uvicorn пишет запрошенный
    адрес вместе со строкой запроса. Текст собирается из msg и args заранее,
    поэтому после фильтра у записи args нет.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Прячет токен в записи; запись всегда пропускается."""
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — кривую запись пусть покажет сам logging
            return True
        if "token=" in message:
            record.msg, record.args = _TOKEN.sub(HIDDEN, message), None
        return True


# то же правило — config/manifest.py (SECRET_NAME, MASK); равенство проверяет тест
SECRET_KEY = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.IGNORECASE)
MASKED = "•••"


def declared_secrets(connectors: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    """Ключи env, объявленные коннекторами секретами: {id: {ключ}} (из settings в connectors())."""
    result: dict[str, set[str]] = {}
    for item in connectors:
        settings = cast(list[Mapping[str, Any]], item.get("settings") or [])
        result[str(item.get("id"))] = {str(s.get("key")) for s in settings if s.get("type") == "secret"}
    return result


def mask_connector_secrets(
    config: dict[str, Any], declared: Mapping[str, Set[str]] | None = None
) -> dict[str, Any]:
    """Копия ответа GET /config, где непустые значения env-секретов коннекторов — «•••».

    Секрет — ключ, в имени которого есть TOKEN, KEY, SECRET или PASSWORD (без учёта регистра),
    или объявленный коннектором секретом: declared — {id: {ключ}}. Назад «•••» значит «не менять».
    """
    effective = config.get("effective")
    connectors = effective.get("connectors") if isinstance(effective, dict) else None
    if not isinstance(connectors, list):
        return config
    secrets = declared or {}
    masked = [_masked(item, secrets) for item in cast(list[object], connectors)]
    return {**config, "effective": {**cast(dict[str, Any], effective), "connectors": masked}}


def _masked(item: object, declared: Mapping[str, Set[str]]) -> object:
    env = item.get("env") if isinstance(item, dict) else None
    if not isinstance(env, dict):
        return item
    own = declared.get(str(cast(dict[str, object], item).get("id")), set[str]())
    hidden = {
        key: MASKED if (SECRET_KEY.search(str(key)) or key in own) and value else value
        for key, value in cast(dict[object, object], env).items()
    }
    return {**cast(dict[str, object], item), "env": hidden}
