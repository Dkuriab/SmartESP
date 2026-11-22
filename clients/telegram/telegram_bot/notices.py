"""Сообщения ядру, когда бота запустило оно: строки JSON в stdout (ядро их читает)."""

from __future__ import annotations

import json
import re
import sys
from typing import TextIO

USERS_KEY = "TELEGRAM_USERS"
_UNSAFE = re.compile(r"[=;\n\r]+")  # разделители списка «id=имя;…» — из имени убираем


class StrangerNotices:
    """Незнакомый написал боту → предложение «Добавить» в приложении (одно на человека)."""

    def __init__(self, out: TextIO | None = None) -> None:
        self._out = out or sys.stdout
        self._seen: set[int] = set()

    def __call__(self, user_id: int, name: str) -> None:
        if user_id in self._seen:
            return
        self._seen.add(user_id)
        clean = " ".join(_UNSAFE.sub(" ", name).split()) or "без имени"
        suggestion = {
            "key": USERS_KEY,
            "value": f"{user_id}={clean}",
            "text": f"Написал(а) боту: {clean} (id {user_id})",
        }
        print(json.dumps({"suggest": suggestion}, ensure_ascii=False), file=self._out, flush=True)
