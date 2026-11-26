"""Объявление ядра в сети: публикует при старте, следит за адресами Mac, снимает при остановке."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from smartesp.contracts import Registrar, ServiceRecord

_log = logging.getLogger(__name__)

CHECK_S = 30.0  # как часто сверять адреса Mac (сменился IP — колонка найдёт новый)


class Advertiser:
    """Публикация службы ядра; ошибки — в журнал, ядро работает дальше, повтор — на следующей сверке.

    make_registrar — новый регистратор на каждую публикацию; record_for — запись для адресов;
    addresses — текущие IPv4-адреса Mac.
    """

    def __init__(
        self,
        make_registrar: Callable[[], Registrar],
        record_for: Callable[[tuple[str, ...]], ServiceRecord],
        addresses: Callable[[], tuple[str, ...]],
        *,
        check_s: float = CHECK_S,
    ) -> None:
        self._make = make_registrar
        self._record_for = record_for
        self._addresses = addresses
        self._check_s = check_s
        self._registrar: Registrar | None = None
        self._published: tuple[str, ...] | None = None  # адреса последней удачной сверки
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Запускает фон: публикация сразу, затем сверка адресов раз в check_s."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="discovery")

    async def refresh(self) -> None:
        """Одна сверка: адреса сменились (или прошлая публикация не удалась) — перепубликовать."""
        try:
            addresses = self._addresses()
        except OSError as error:
            _log.warning("Объявление в сети: адреса Mac не прочитаны: %s", error)
            return
        if addresses == self._published:
            return
        await self._withdraw()
        if not addresses:
            _log.info("Объявление в сети: у Mac нет адреса в локальной сети, жду")
            self._published = addresses
            return
        registrar: Registrar | None = None
        try:
            record = self._record_for(addresses)  # id ядра — из папки данных (может не записаться)
            registrar = self._make()
            await registrar.register(record)
        except Exception as error:  # noqa: BLE001 — любая ошибка сети не должна ронять ядро
            _log.warning("Объявление в сети: не удалось объявить ядро: %s", error)
            if registrar is not None:
                await self._close(registrar)
            return
        self._registrar, self._published = registrar, addresses
        _log.info("Объявление в сети: _smartesp._tcp id %s, %s:%d", record.core_id, addresses, record.port)

    async def aclose(self) -> None:
        """Останавливает фон и снимает публикацию. Повторный вызов безопасен."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._withdraw()

    async def _run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self._check_s)

    async def _withdraw(self) -> None:
        registrar, self._registrar = self._registrar, None
        self._published = None
        if registrar is not None:
            await self._close(registrar)

    @staticmethod
    async def _close(registrar: Registrar) -> None:
        try:
            await registrar.aclose()
        except Exception as error:  # noqa: BLE001
            _log.warning("Объявление в сети: не удалось снять объявление: %s", error)
