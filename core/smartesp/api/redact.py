"""Фильтр журнала: прячет токен из `?token=…` (WebSocket событий, адрес интерфейса)."""

from __future__ import annotations

import logging
import re

_TOKEN = re.compile(r"token=[^&\s\"']+")
HIDDEN = "token=***"


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
