"""Ход работы: человеку — строки в терминал, ядру (--json) — строки JSON в stdout.

JSON: {"stage": "…", "done": n, "total": m} — ход; {"result": {…}} — итог; {"log": "…"} — журнал.
"""

from __future__ import annotations

import json
import sys
import time

_json = False
_last: dict[str, float] = {}


def use_json(on: bool) -> None:
    """Включает вывод строками JSON (для ядра)."""
    global _json
    _json = on


def _emit(data: dict[str, object], text: str) -> None:
    print(json.dumps(data, ensure_ascii=False) if _json else text, flush=True)


def step(stage: str, done: int, total: int, *, every_s: float = 1.0) -> None:
    """Ход стадии; чаще раза в every_s секунд не пишет (кроме конца)."""
    now = time.monotonic()
    if done < total and now - _last.get(stage, 0.0) < every_s:
        return
    _last[stage] = now
    percent = f" ({100 * done // total}%)" if total else ""
    _emit({"stage": stage, "done": done, "total": total}, f"  {stage}: {done} из {total}{percent}")


def log(text: str) -> None:
    """Строка журнала."""
    _emit({"log": text}, text)


def result(data: dict[str, object]) -> None:
    """Итог шага."""
    _emit({"result": data}, json.dumps(data, ensure_ascii=False, indent=2))


def fail(text: str) -> None:
    """Понятная ошибка и выход с кодом 1."""
    _emit({"error": text}, f"Ошибка: {text}")
    sys.exit(1)
