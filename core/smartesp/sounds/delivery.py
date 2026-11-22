"""Доставка звуков на колонки: при подключении и после изменений — только отличия, по одному.

Что лежит на колонке, ядро знает из её hello (SHA-256 своих звуков) и из итогов своих update.
У колонки одно скачивание за раз, поэтому звуки ей шлются по очереди с ожиданием итога.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

from smartesp.contracts import (
    SOUND_TONES,
    EventSink,
    SoundDelivery,
    SoundTargets,
    SoundTone,
    UpdateRefusedError,
    UpdateWhat,
)

from .library import SoundLibrary

_log = logging.getLogger(__name__)
RESULT_TIMEOUT_S = 30.0  # звук до 96 КБ по локальной сети — секунды; дольше — колонка не ответила
NO_ANSWER = "колонка не ответила"
LOST_FILE = "файл звука пропал из папки данных"
ERRORS = {
    "busy": "колонка занята другим обновлением",
    "download": "не скачался (связь с ядром)",
    "size": "размер не тот",
    "hash": "файл повредился по дороге",
    "write": "не записался во флеш",
    "storage": "нет места во флеше колонки",
}

type Install = Callable[[str, UpdateWhat, bytes, Mapping[str, object] | None], Awaitable[None]]


class SoundDeliveries:
    """Доставка по колонкам и её состояние для обзора; события sounds {device_id}."""

    def __init__(
        self,
        library: SoundLibrary,
        targets: SoundTargets,
        install: Install,
        events: EventSink | None = None,
        timeout_s: float = RESULT_TIMEOUT_S,
    ) -> None:
        self._library = library
        self._targets = targets
        self._install = install
        self._events = events
        self._timeout_s = timeout_s
        self._actual: dict[str, dict[str, str | None]] = {}  # колонка → сигнал → SHA-256 на ней
        self._supported: dict[str, bool] = {}  # по последнему hello
        self._states: dict[tuple[str, str], tuple[SoundDelivery, str]] = {}  # идёт или не вышло
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._again: set[str] = set()  # пока шла доставка, что-то изменилось — пройти ещё раз

    def connected(self, device_id: str) -> None:
        """Колонка подключилась: её звуки — из hello; досылаем отличия."""
        reported = self._targets.device_sounds(device_id)
        self._supported[device_id] = reported is not None
        self._clear(device_id)
        if reported is None:
            self._actual.pop(device_id, None)
            self._publish(device_id)
            return
        self._actual[device_id] = {tone: reported.get(tone) for tone in SOUND_TONES}
        self.start(device_id)

    def start_all(self, *, retry: bool = False) -> None:
        """Доставка на все колонки, которые сейчас на связи и умеют звуки; retry — забыть неудачи."""
        for device_id in [d for d, ok in self._supported.items() if ok]:
            if self._targets.device_sounds(device_id) is not None:
                if retry:
                    self._clear(device_id)
                self.start(device_id)

    def changed(self, tone: SoundTone) -> None:
        """Назначение сигнала изменилось: прежние неудачи по нему забыты, доставка на все колонки."""
        for key in [key for key in self._states if key[1] == tone]:
            del self._states[key]
        self._publish(None)
        self.start_all()

    def start(self, device_id: str) -> None:
        """Сверяет колонку с назначениями (в фоне); уже идёт — пройдёт ещё раз после."""
        worker = self._workers.get(device_id)
        if worker is not None and not worker.done():
            self._again.add(device_id)
            return
        self._workers[device_id] = asyncio.create_task(self._work(device_id), name=f"sounds-{device_id}")

    def state(self, device_id: str, tone: SoundTone, connected: bool) -> tuple[SoundDelivery, str]:
        """Доставка сигнала на колонку и текст ошибки."""
        if self._supported.get(device_id) is False:
            return "unsupported", ""
        if (device_id, tone) in self._states:
            return self._states[(device_id, tone)]
        actual = self._actual.get(device_id)
        if actual is not None and actual.get(tone) == self._library.wanted(device_id, tone):
            return "ok", ""
        return ("pending" if connected and actual is not None else "offline"), ""

    def supported(self, device_id: str) -> bool | None:
        """Умеет ли колонка звуки по последнему hello; None — не подключалась."""
        return self._supported.get(device_id)

    async def aclose(self) -> None:
        """Снимает доставки."""
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _work(self, device_id: str) -> None:
        try:
            while True:
                self._again.discard(device_id)
                await self._sync(device_id)
                if device_id not in self._again:
                    return
        except Exception:
            _log.exception("Доставка звуков на %s сломалась", device_id)

    async def _sync(self, device_id: str) -> None:
        """Шлёт по очереди все сигналы, где на колонке не то; колонка ушла — стоп."""
        for tone in SOUND_TONES:
            actual = self._actual.get(device_id)
            if actual is None or self._targets.device_sounds(device_id) is None:
                return
            wanted = self._library.wanted(device_id, tone)
            if actual.get(tone) == wanted:
                continue
            if self._states.get((device_id, tone), ("", ""))[0] == "failed":
                continue  # не вышло — повтор по кнопке или при следующем подключении
            if not await self._send(device_id, tone, wanted):
                return

    async def _send(self, device_id: str, tone: SoundTone, sha256: str | None) -> bool:
        """Один звук (None — встроенный) и ожидание итога. False — колонка недоступна."""
        data = self._library.pcm(sha256) if sha256 is not None else b""
        if data is None:
            self._set(device_id, tone, "failed", LOST_FILE)
            return True
        self._set(device_id, tone, "sending", "")
        result = self._targets.expect_sound(device_id, tone)
        try:
            await self._install(device_id, "sound", data, {"tone": tone})
            progress = await asyncio.wait_for(result, self._timeout_s)
        except UpdateRefusedError as error:
            result.cancel()
            self._set(device_id, tone, "failed", str(error))
            return False
        except TimeoutError:
            self._set(device_id, tone, "failed", NO_ANSWER)
            return True
        if progress.state != "done":
            self._set(device_id, tone, "failed", ERRORS.get(progress.error, progress.error or "ошибка"))
            return True
        self._actual.setdefault(device_id, {})[tone] = sha256
        self._states.pop((device_id, tone), None)
        self._publish(device_id)
        _log.info("Звук %s на %s: %s", tone, device_id, "свой" if sha256 else "встроенный")
        return True

    def _set(self, device_id: str, tone: str, delivery: SoundDelivery, error: str) -> None:
        self._states[(device_id, tone)] = (delivery, error)
        if delivery == "failed":
            _log.warning("Звук %s на %s не доставлен: %s", tone, device_id, error)
        self._publish(device_id)

    def _clear(self, device_id: str) -> None:
        for key in [key for key in self._states if key[0] == device_id]:
            del self._states[key]

    def _publish(self, device_id: str | None) -> None:
        if self._events is not None:
            self._events.publish("sounds", {"device_id": device_id})
