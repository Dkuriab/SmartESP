"""Потоки звука в хабе (протокол 5): команды stream_* колонке и её отчёты stream_status."""

from __future__ import annotations

import logging
from collections.abc import Callable

from smartesp.contracts import STREAM_RATE, StreamCommand, StreamListener, StreamReport

from .messages import stream as stream_frame
from .session import Session

STREAM_PROTOCOL = 5  # с этой версии (прошивка 0.6.0) колонка сама тянет поток по ссылке
CORE_RATES = (16000, 48000)  # частоты потоков, которые умеет ядро (ffmpeg -ar)

logger = logging.getLogger(__name__)


class StreamRelay:
    """Команды потока — подключённой колонке v5; отчёты и отключения — слушателю (один на хаб)."""

    def __init__(self, session: Callable[[str], Session | None]) -> None:
        """session(device_id) — открытая сессия колонки или None."""
        self._session = session
        self._listener: StreamListener | None = None

    def use_listener(self, listener: StreamListener) -> None:
        """Слушатель отчётов; новый заменяет прежний."""
        self._listener = listener

    def supports(self, device_id: str) -> bool:
        """Колонка подключена и её протокол ≥ 5."""
        session = self._session(device_id)
        return session is not None and session.protocol >= STREAM_PROTOCOL

    def rate(self, device_id: str) -> int:
        """Наибольшая частота, которую умеют и ядро, и колонка (hello stream_rates); нет — 16 кГц."""
        session = self._session(device_id)
        common = set(CORE_RATES) & set(session.stream_rates if session is not None else ())
        return max(common, default=STREAM_RATE)

    async def send(self, device_id: str, command: StreamCommand) -> bool:
        """Шлёт команду; False — колонка не подключена, протокол < 5 или связь оборвалась."""
        session = self._session(device_id)
        if session is None or session.protocol < STREAM_PROTOCOL:
            return False
        return await session.send(stream_frame(command))

    def report(self, device_id: str, report: StreamReport | None) -> None:
        """Отчёт колонки (None — отключилась) → слушателю; его сбой хаб не роняет."""
        if self._listener is None:
            return
        try:
            self._listener(device_id, report)
        except Exception:  # noqa: BLE001 — колонка важнее потока
            logger.exception("Слушатель потоков упал на отчёте %s", device_id)
