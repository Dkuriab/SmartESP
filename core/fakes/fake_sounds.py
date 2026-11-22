"""Подделки для звуков: колонки (SoundTargets) с установкой звука, которая сразу отвечает итогом."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from smartesp.contracts import DeviceInfo, UpdateProgress, UpdateRefusedError, UpdateWhat


class FakeSoundTargets:
    """Колонки: id → (на связи, хэши звуков из hello или None — прошивка без звуков).

    install — как Updates.install: запоминает отправку и отвечает итогом result (None — молчит).
    """

    def __init__(self) -> None:
        self.speakers: dict[str, tuple[bool, dict[str, str] | None]] = {}
        self.sent: list[tuple[str, str, bytes]] = []  # (колонка, сигнал, данные)
        self.result: str | None = "done"
        self.error = ""
        self.refuse = False
        self._waiters: dict[tuple[str, str], asyncio.Future[UpdateProgress]] = {}

    def devices(self) -> list[DeviceInfo]:
        return [DeviceInfo(d, d, on, "", "", None) for d, (on, _) in self.speakers.items()]

    def device_sounds(self, device_id: str) -> Mapping[str, str] | None:
        on, sounds = self.speakers.get(device_id, (False, None))
        return dict(sounds) if on and sounds is not None else None

    def expect_sound(self, device_id: str, tone: str) -> asyncio.Future[UpdateProgress]:
        future: asyncio.Future[UpdateProgress] = asyncio.get_running_loop().create_future()
        self._waiters[(device_id, tone)] = future
        return future

    async def install(
        self, device_id: str, what: UpdateWhat, data: bytes, meta: Mapping[str, object] | None = None
    ) -> None:
        assert what == "sound" and meta is not None
        if self.refuse:
            raise UpdateRefusedError("колонка не подключена")
        tone = str(meta["tone"])
        self.sent.append((device_id, tone, data))
        future = self._waiters.get((device_id, tone))
        if self.result is not None and future is not None and not future.done():
            progress = UpdateProgress("sound", self.result, len(data), len(data), self.error, 0.0)
            asyncio.get_running_loop().call_soon(lambda: future.done() or future.set_result(progress))
