"""Обновления колонок по воздуху в хабе: что отправлено и что колонка сообщила (update_status)."""

from __future__ import annotations

import time
from collections.abc import Callable

from smartesp.contracts import UpdateProgress

from .messages import UpdateStatus

UPDATE_PROTOCOL = 4  # колонка с этим протоколом (прошивка 0.5.0+) умеет update


class UpdateStates:
    """Последнее обновление каждой колонки; on_change(device_id, состояние) — при каждом изменении."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._states: dict[str, UpdateProgress] = {}
        self._clock = clock
        self.on_change: Callable[[str, UpdateProgress], None] = lambda device_id, progress: None

    def get(self, device_id: str) -> UpdateProgress | None:
        """Последнее обновление колонки или None."""
        return self._states.get(device_id)

    def sent(self, device_id: str, what: str, total: int) -> None:
        """Команда update ушла колонке."""
        self._set(device_id, UpdateProgress(what, "sent", 0, total, "", self._clock()))

    def apply(self, device_id: str, status: UpdateStatus) -> None:
        """Колонка сообщила ход или итог."""
        self._set(
            device_id,
            UpdateProgress(status.what, status.state, status.done, status.total, status.error, self._clock()),
        )

    def _set(self, device_id: str, progress: UpdateProgress) -> None:
        self._states[device_id] = progress
        self.on_change(device_id, progress)
