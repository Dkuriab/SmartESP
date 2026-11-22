"""API ядра для потоков: очередь на колонку, управление, громкость, состояние; плейлисты станций.

Адрес и токен ядро даёт коннектору само (флаг core_api в smartesp.json): SMARTESP_URL, SMARTESP_TOKEN.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import httpx

TIMEOUT_S = 15.0  # звук Mac: ядро проверяет устройство ввода (запуск ffmpeg)
PLAYLIST_BYTES = 64 * 1024


class CoreError(Exception):
    """Ядро отказало или недоступно; текст — для человека."""


type Stream = dict[str, Any]


class CoreApi:
    """Ходит в /api/v1/streams ядра."""

    def __init__(self, env: Mapping[str, str], transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = env.get("SMARTESP_URL", "").rstrip("/")
        self._token = env.get("SMARTESP_TOKEN", "")
        self._transport = transport

    async def streams(self) -> list[Stream]:
        """Колонки, умеющие потоки, и что на них."""
        return cast(list[Stream], await self._call("GET", "/api/v1/streams"))

    async def play(
        self, device_id: str | None, items: list[dict[str, str]], volume: float | None = None
    ) -> Stream:
        body: dict[str, object] = {"device_id": device_id, "items": items}
        if volume is not None:
            body["volume"] = volume
        return cast(Stream, await self._call("POST", "/api/v1/streams", body))

    async def control(self, device_id: str | None, action: str) -> Stream:
        body = {"device_id": device_id, "action": action}
        return cast(Stream, await self._call("POST", "/api/v1/streams/control", body))

    async def volume(
        self, device_id: str | None, *, volume: float | None = None, delta: float = 0.0
    ) -> Stream:
        body = {"device_id": device_id, "volume": volume, "delta": delta}
        return cast(Stream, await self._call("POST", "/api/v1/streams/volume", body))

    async def _call(self, method: str, path: str, body: object = None) -> object:
        if not self._url or not self._token:
            raise CoreError("Коннектору не дали адрес ядра: нужен флаг core_api в smartesp.json.")
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S) as client:
                response = await client.request(method, self._url + path, json=body, headers=headers)
        except httpx.HTTPError as error:
            raise CoreError("Ядро не отвечает.") from error
        if response.status_code >= 400:
            raise CoreError(_detail(response))
        return response.json()


def _detail(response: httpx.Response) -> str:
    """Текст отказа ядра (detail) или код."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else f"Ядро ответило ошибкой {response.status_code}."


def is_playlist(url: str) -> bool:
    """Ссылка на текстовый плейлист станции (.m3u/.pls), а не на сам поток (.m3u8 — HLS: его читает
    ffmpeg в ядре)."""
    path = httpx.URL(url).path.lower()
    return path.endswith((".m3u", ".pls"))


async def resolve_station(url: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Плейлист .m3u/.pls → первая ссылка http(s) из него; поток — как есть."""
    if not is_playlist(url):
        return url
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise CoreError("Плейлист станции не открылся.") from error
    for line in response.text[:PLAYLIST_BYTES].splitlines():
        value = line.split("=", 1)[1] if line.lower().startswith("file") and "=" in line else line
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return value
    raise CoreError("В плейлисте станции нет ссылки на поток.")
