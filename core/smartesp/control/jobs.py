"""Задания очереди изменений: правка настроек или пересборка разделов (внутреннее)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rebuild:
    """Пересборка разделов names по записанным настройкам; итог — в done."""

    names: tuple[str, ...]
    done: asyncio.Future[None]


Job = tuple[int, dict[str, Any]] | Rebuild  # (номер правки, правка) или пересборка


def settle(done: asyncio.Future[None], error: Exception | None) -> None:
    """Итог пересборки; тот, кто ждал, мог уже уйти (его отмена отменяет и done)."""
    if done.done():
        return
    if error is None:
        done.set_result(None)
    else:
        done.set_exception(error)
