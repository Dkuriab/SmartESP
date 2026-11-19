"""Память выбора: на «Уточни: …» человек выбрал вариант — запомнить, как он назвал продукт.

Файл `pending.json` в папке человека: что сказано и какие варианты предложены.
Действует недолго: выбор засчитывается, только если запись сделана вскоре после вопроса.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from .storage import read_text, write_atomic

FILE = "pending.json"
WINDOW = timedelta(minutes=15)


def remember(root: Path, said: str, options: tuple[str, ...], now: datetime) -> None:
    """Запоминает вопрос: сказанное и предложенные варианты."""
    data = {"said": said, "options": list(options), "time": now.isoformat(timespec="seconds")}
    write_atomic(root / FILE, json.dumps(data, ensure_ascii=False) + "\n")


def take(root: Path, chosen: str, now: datetime) -> str:
    """Забывает вопрос и возвращает сказанное тогда, если `chosen` — один из вариантов
    и прошло не больше 15 минут; иначе пустая строка.
    """
    path = root / FILE
    text = read_text(path)
    path.unlink(missing_ok=True)
    try:
        data = json.loads(text)
        asked = datetime.fromisoformat(data["time"])
        said, options = str(data["said"]), [str(o) for o in data["options"]]
    except (ValueError, KeyError, TypeError):
        return ""
    if chosen in options and timedelta(0) <= now - asked <= WINDOW:
        return said
    return ""
