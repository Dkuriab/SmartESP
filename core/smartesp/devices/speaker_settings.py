"""Настройки колонок в хабе: громкость, обновления по воздуху, свои звуки, слушатели подключения.

Основа CoreTurns (а значит, и DeviceHub): сессии и фоновые отправки — у них, здесь — только то,
что колонке шлётся помимо ходов.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any

from smartesp.contracts import SOUNDS_CAP, DeviceInfo, UpdateProgress

from .messages import update as update_frame
from .messages import volume as volume_frame
from .session import Session
from .updates import UPDATE_PROTOCOL, UpdateStates

DEFAULT_VOLUME = 50  # %, как у прошивки по умолчанию

logger = logging.getLogger(__name__)


class SpeakerSettings:
    """Громкость, обновления и звуки колонок; сессии (_sessions) и отправку (_spawn) даёт наследник."""

    _sessions: dict[str, Session]

    def __init__(self) -> None:
        self._volumes: dict[str, int] = {}  # громкость колонок из настроек, %
        self._updates = UpdateStates()  # обновления по воздуху: что отправлено и что ответила колонка
        self._updates.on_change = lambda device, progress: self._publish(
            "device_update", {"device_id": device, **vars(progress)}
        )
        self._connect_listeners: list[Callable[[str], None]] = []  # колонка подключилась (после hello)

    def _publish(self, kind: str, data: dict[str, object]) -> None:
        """Событие для интерфейса; хаб переопределяет (у него приёмник событий)."""

    def _spawn(self, coro: Coroutine[Any, Any, object], what: str) -> None:
        """Отправка в фоне; реализует CoreTurns."""
        raise NotImplementedError

    def volume_of(self, device_id: str) -> int:
        """Громкость колонки из настроек, % (не задана — как у прошивки по умолчанию)."""
        return self._volumes.get(device_id, DEFAULT_VOLUME)

    def set_volumes(self, volumes: dict[str, int]) -> None:
        """Громкость колонок из настроек; подключённым с изменившейся — сразу кадр volume."""
        old, self._volumes = self._volumes, dict(volumes)
        for device_id, session in self._sessions.items():
            if self.volume_of(device_id) != old.get(device_id, DEFAULT_VOLUME):
                self._send_volume(session)

    def _with_state(self, devices: list[DeviceInfo]) -> list[DeviceInfo]:
        """Сведения о колонках с громкостью из настроек и последним обновлением по воздуху."""
        return [
            replace(d, update=self._updates.get(d.device_id), volume=self.volume_of(d.device_id))
            for d in devices
        ]

    def _send_volume(self, session: Session) -> None:
        """Громкость — колонке (при подключении: колонка после перезагрузки её не помнит)."""
        frame = volume_frame(self.volume_of(session.device_id))
        self._spawn(session.send(frame), f"volume to {session.device_id}")

    def supports_update(self, device_id: str) -> bool:
        """Колонка подключена и умеет обновляться по воздуху (протокол ≥ 4, прошивка 0.5.0+)."""
        session = self._sessions.get(device_id)
        return session is not None and session.protocol >= UPDATE_PROTOCOL

    def add_connect_listener(self, listener: Callable[[str], None]) -> None:
        """listener(device_id) — после каждого hello колонки (сессия уже открыта)."""
        self._connect_listeners.append(listener)

    def device_sounds(self, device_id: str) -> dict[str, str] | None:
        """SHA-256 своих звуков колонки из hello; None — не подключена или прошивка без звуков."""
        session = self._sessions.get(device_id)
        return dict(session.sounds) if session is not None and SOUNDS_CAP in session.caps else None

    def expect_sound(self, device_id: str, tone: str) -> asyncio.Future[UpdateProgress]:
        """Ожидание итога следующего update звука tone на колонке (update_status done | failed)."""
        return self._updates.expect_sound(device_id, tone)

    def _connected(self, device_id: str) -> None:
        """Сообщает слушателям о подключении; ошибка слушателя хаб не роняет."""
        for listener in self._connect_listeners:
            try:
                listener(device_id)
            except Exception:
                logger.exception("connect listener failed")

    async def send_update(self, device_id: str, payload: dict[str, object]) -> bool:
        """Шлёт колонке команду update (см. messages.update); False — не умеет или не подключена.

        Звук (what sound) — только колонке с возможностью sounds: старая прошивка команду отбросит.
        """
        session = self._sessions.get(device_id)
        if session is None or not self.supports_update(device_id):
            return False
        if payload.get("what") == "sound" and SOUNDS_CAP not in session.caps:
            return False
        if not await session.send(update_frame(payload)):
            return False
        self._updates.sent(device_id, str(payload.get("what", "")), int(payload.get("size", 0)))  # type: ignore[call-overload]
        return True
