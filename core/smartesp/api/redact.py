"""Сокрытие: токен из `?token=…` в журнале, секреты окружения коннекторов в GET /config."""

from __future__ import annotations

import logging
import re
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


_SECRET_KEY = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.IGNORECASE)
MASKED = "•••"


def mask_connector_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Копия ответа GET /config, где непустые значения env коннекторов с ключом-секретом — «•••».

    Секрет — ключ, в имени которого есть TOKEN, KEY, SECRET или PASSWORD (без учёта регистра).
    Править env через API всё равно нельзя, поэтому значения обратно не нужны.
    """
    effective = config.get("effective")
    connectors = effective.get("connectors") if isinstance(effective, dict) else None
    if not isinstance(connectors, list):
        return config
    masked = [_masked(item) for item in cast(list[object], connectors)]
    return {**config, "effective": {**cast(dict[str, Any], effective), "connectors": masked}}


def _masked(item: object) -> object:
    env = item.get("env") if isinstance(item, dict) else None
    if not isinstance(env, dict):
        return item
    hidden = {
        key: MASKED if _SECRET_KEY.search(str(key)) and value else value
        for key, value in cast(dict[object, object], env).items()
    }
    return {**cast(dict[str, object], item), "env": hidden}
