"""Связь с API ядра: колонки (из сводки) и их громкость (правка настроек devices)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT_S = 5.0


class CoreUnavailableError(Exception):
    """Ядро не ответило или отказало."""


@dataclass(frozen=True)
class Speaker:
    """Колонка: id (MAC), имя, в сети ли, громкость, %."""

    id: str
    name: str
    online: bool
    volume: int


class CoreApi:
    """Клиент API ядра; адрес и токен — из окружения (их передаёт ядро: core_api в smartesp.json)."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._url = (url or os.environ.get("SMARTESP_URL", "")).rstrip("/")
        self._token = token or os.environ.get("SMARTESP_TOKEN", "")
        self._transport = transport

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if not self._url or not self._token:
            raise CoreUnavailableError("нет адреса или токена ядра (коннектор запущен не ядром)")
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = await client.request(
                    method, f"{self._url}/api/v1{path}", json=body, headers=headers
                )
        except httpx.HTTPError as error:
            raise CoreUnavailableError(f"ядро не отвечает ({type(error).__name__})") from error
        if response.status_code >= 400:
            raise CoreUnavailableError(f"ядро отказало: {response.status_code}")
        return response.json() if response.content else None

    async def speakers(self) -> list[Speaker]:
        """Колонки из сводки ядра."""
        status = await self._request("GET", "/status")
        return [
            Speaker(
                str(d["device_id"]),
                str(d.get("name") or d["device_id"]),
                bool(d.get("connected")),
                int(d.get("volume", 50)),
            )
            for d in status.get("devices", [])
        ]

    async def set_volume(self, speaker_id: str, percent: int) -> None:
        """Громкость колонки в настройках ядра (ядро сразу шлёт её колонке)."""
        await self._request("PATCH", "/config", {"devices": {speaker_id: {"volume": percent}}})
