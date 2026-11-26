"""Действия коннектора: что поставить в очередь, на какую колонку, и ответ для модели по-русски."""

from __future__ import annotations

import random
from collections.abc import Awaitable

import httpx

from music_mcp.core import CoreApi, CoreError, Stream, resolve_station
from music_mcp.library import Library, LibraryError, normalize

CAPTURE_PREFIX = "capture:"  # источник ядра «звук Mac с устройства ввода»


class MusicError(Exception):
    """Ошибка для модели (по-русски)."""


class Music:
    """library — настройки; core — API ядра; transport — сеть для плейлистов станций (тесты)."""

    def __init__(
        self,
        library: Library,
        core: CoreApi,
        transport: httpx.AsyncBaseTransport | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._library = library
        self._core = core
        self._transport = transport
        self._rng = rng

    async def play_files(self, query: str, speaker: str, shuffle: bool, here: str | None) -> str:
        """Файлы по запросу на колонку speaker (пусто — here, где говорят)."""
        try:
            tracks = self._library.find(query, shuffle=shuffle, rng=self._rng)
        except LibraryError as error:
            raise MusicError(str(error)) from None
        items = [{"source": t.path, "title": t.title} for t in tracks]
        return await self._play(items, speaker, here)

    async def play_radio(self, station: str, speaker: str, here: str | None) -> str:
        try:
            name, url = self._library.station(station)
            url = await resolve_station(url, self._transport)
        except (LibraryError, CoreError) as error:
            raise MusicError(str(error)) from None
        return await self._play([{"source": url, "title": f"Радио «{name}»"}], speaker, here)

    async def play_mac(self, speaker: str, here: str | None) -> str:
        source = CAPTURE_PREFIX + self._library.mac_device
        return await self._play([{"source": source, "title": "Звук Mac"}], speaker, here)

    async def control(self, action: str, speaker: str) -> str:
        device = await self._device(speaker) if speaker else None
        return _describe(await _ask(self._core.control(device, action)))

    async def volume(self, delta: int | None, percent: int | None, speaker: str) -> str:
        """Сдвиг delta важнее percent (модели шлют «percent: 0» рядом со сдвигом); нет обоих — узнать."""
        if not delta and percent is not None and percent < 0:
            raise MusicError("Громкость — от 0 до 100 процентов; «тише на 20» — delta -20.")
        device = await self._device(speaker) if speaker else None
        if delta:
            state = await _ask(self._core.volume(device, delta=max(min(delta, 100), -100) / 100))
        elif percent is not None:
            state = await _ask(self._core.volume(device, volume=min(percent, 100) / 100))
        else:
            state = await _ask(self._core.volume(device))
        return f"Громкость музыки на колонке «{state['name']}»: {round(state['volume'] * 100)}%."

    async def status(self) -> str:
        streams = await _ask(self._core.streams())
        if not streams:
            return "Колонок, которые умеют музыку, сейчас нет в сети."
        return " ".join(_describe(s) for s in streams)

    def library(self) -> str:
        return self._library.describe()

    async def _play(self, items: list[dict[str, str]], speaker: str, here: str | None) -> str:
        device = await self._device(speaker) if speaker else here
        return _describe(await _ask(self._core.play(device, items)))

    async def _device(self, speaker: str) -> str:
        """Колонка по имени или его части."""
        streams = await _ask(self._core.streams())
        wanted = normalize(speaker).strip()
        for stream in streams:
            if wanted in normalize(str(stream["name"])) or normalize(str(stream["name"])) in wanted:
                return str(stream["device_id"])
        names = ", ".join(f"«{s['name']}»" for s in streams) or "нет ни одной"
        raise MusicError(f"Нет колонки «{speaker}», которая умеет музыку. Есть: {names}.")


async def _ask[T](call: Awaitable[T]) -> T:
    """Ответ ядра; отказ — MusicError с его текстом."""
    try:
        return await call
    except CoreError as error:
        raise MusicError(str(error)) from None


def _describe(state: Stream) -> str:
    """Состояние колонки одной фразой."""
    name, title = state.get("name", ""), state.get("title", "")
    where = f"На колонке «{name}»"
    error = f" ({state['error']})" if state.get("error") else ""
    if state.get("state") == "playing":
        count = int(state.get("count", 0))
        place = f" ({int(state.get('index', 0)) + 1} из {count})" if count > 1 else ""
        return f"{where} играет «{title}»{place}."
    if state.get("state") == "paused":
        return f"{where} на паузе «{title}»{error}."
    return f"{where} ничего не играет{error}."
