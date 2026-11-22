"""Обновления колонок по воздуху в хабе: что отправлено и что колонка сообщила (update_status).

Звуки сигналов в «последнее обновление» колонки не попадают (панель прошивки о них не говорит):
их итог получает тот, кто ждёт его через expect_sound.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from smartesp.contracts import UpdateProgress

from .messages import UpdateStatus

UPDATE_PROTOCOL = 4  # колонка с этим протоколом (прошивка 0.5.0+) умеет update
SOUND = "sound"
FINAL = ("done", "failed")


class UpdateStates:
    """Последнее обновление каждой колонки; on_change(device_id, состояние) — при каждом изменении."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._states: dict[str, UpdateProgress] = {}
        self._clock = clock
        self._sound_waiters: dict[tuple[str, str], list[asyncio.Future[UpdateProgress]]] = {}
        self.on_change: Callable[[str, UpdateProgress], None] = lambda device_id, progress: None

    def get(self, device_id: str) -> UpdateProgress | None:
        """Последнее обновление колонки или None."""
        return self._states.get(device_id)

    def expect_sound(self, device_id: str, tone: str) -> asyncio.Future[UpdateProgress]:
        """Ожидание итога (done | failed) следующего update звука tone на колонке device_id."""
        future: asyncio.Future[UpdateProgress] = asyncio.get_running_loop().create_future()
        self._sound_waiters.setdefault((device_id, tone), []).append(future)
        return future

    def sent(self, device_id: str, what: str, total: int) -> None:
        """Команда update ушла колонке."""
        if what == SOUND:
            return
        self._set(device_id, UpdateProgress(what, "sent", 0, total, "", self._clock()))

    def apply(self, device_id: str, status: UpdateStatus) -> None:
        """Колонка сообщила ход или итог."""
        at = self._clock()
        progress = UpdateProgress(status.what, status.state, status.done, status.total, status.error, at)
        if status.what != SOUND:
            self._set(device_id, progress)
        elif status.state in FINAL:
            for future in self._sound_waiters.pop((device_id, status.tone), []):
                if not future.done():
                    future.set_result(progress)

    def _set(self, device_id: str, progress: UpdateProgress) -> None:
        self._states[device_id] = progress
        self.on_change(device_id, progress)
