"""Калибровка эха в хабе (прошивка 0.7.0, возможность «echo»): команды колонке, её echo_status.

Сдвиг образца (на сколько задержать звук динамика перед эхоподавлением) хранит сама колонка; ядро
помнит последнее, что она сообщила, и отдаёт это в DeviceInfo.echo и событием device_echo.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from smartesp.contracts import ECHO_CAP, MAX_ECHO_DELAY_MS, EchoCalibration, EchoRefusedError

from .echo_status import EchoStatus, valid_delay
from .session import Session

NO_DEVICE = "колонка не подключена"
OLD_FIRMWARE = "колонка не умеет калибровку эха — обновите прошивку до 0.7.0"
BUSY = "колонка занята разговором — попробуйте через минуту"
RUNNING = "калибровка уже идёт"
STALE_S = 30.0  # калибровка идёт ~5 с; дольше без итога — считаем потерянной
BAD_DELAY = f"сдвиг — от 0 до {MAX_ECHO_DELAY_MS} мс"


def echo_frame(delay_ms: int | None) -> str:
    """Кадр колонке: echo_calibrate (None) или echo_delay {delay_ms}."""
    if delay_ms is None:
        return json.dumps({"type": "echo_calibrate"})
    return json.dumps({"type": "echo_delay", "delay_ms": delay_ms})


class EchoStates:
    """Последнее состояние сдвига каждой колонки; on_change(device_id, состояние) — при изменении."""

    def __init__(
        self, session: Callable[[str], Session | None], clock: Callable[[], float] = time.time
    ) -> None:
        self._session = session
        self._clock = clock
        self._states: dict[str, EchoCalibration] = {}
        self.on_change: Callable[[str, EchoCalibration], None] = lambda device_id, echo: None

    def get(self, device_id: str) -> EchoCalibration | None:
        return self._states.get(device_id)

    def apply(self, device_id: str, status: EchoStatus) -> None:
        """Колонка сообщила сдвиг или ход калибровки."""
        echo = EchoCalibration(
            status.state,  # type: ignore[arg-type]
            status.delay_ms,
            status.previous_ms,
            status.confidence,
            status.error,
            self._clock(),
        )
        self._set(device_id, echo)

    async def calibrate(self, device_id: str) -> None:
        """echo_calibrate свободной колонке с возможностью «echo»; иначе EchoRefusedError."""
        session = self._check(device_id)
        if not session.is_idle():
            raise EchoRefusedError(BUSY)
        current = self._states.get(device_id)
        if (
            current is not None
            and current.state in ("sent", "running")
            and self._clock() - current.at < STALE_S
        ):
            raise EchoRefusedError(RUNNING)
        if not await session.send(echo_frame(None)):
            raise EchoRefusedError(NO_DEVICE)
        delay = current.delay_ms if current is not None else 0
        self._set(device_id, EchoCalibration("sent", delay, delay, 0.0, "", self._clock()))

    async def set_delay(self, device_id: str, delay_ms: int) -> None:
        """echo_delay колонке (0..300 мс); итог — её echo_status current."""
        if not valid_delay(delay_ms):
            raise EchoRefusedError(BAD_DELAY)
        session = self._check(device_id)
        if not await session.send(echo_frame(delay_ms)):
            raise EchoRefusedError(NO_DEVICE)

    def _check(self, device_id: str) -> Session:
        session = self._session(device_id)
        if session is None:
            raise EchoRefusedError(NO_DEVICE)
        if ECHO_CAP not in session.caps:
            raise EchoRefusedError(OLD_FIRMWARE)
        return session

    def _set(self, device_id: str, echo: EchoCalibration) -> None:
        self._states[device_id] = echo
        self.on_change(device_id, echo)
