"""Кеш одного TTS для образцов голосов и сборка образца в WAV."""

import asyncio
from collections.abc import Awaitable, Callable

from smartesp.contracts import TextToSpeech

from ._progress import to_wav

Key = tuple[str, str]


class PreviewCache:
    """Держит один собранный TTS — последний запрошенный для образца."""

    def __init__(self) -> None:
        self._entry: tuple[Key, TextToSpeech] | None = None
        self._lock = asyncio.Lock()

    async def get(self, key: Key, build: Callable[[Key], Awaitable[TextToSpeech]]) -> TextToSpeech:
        """Возвращает TTS из кеша или собирает через build и заменяет им прежний."""
        async with self._lock:
            if self._entry is not None and self._entry[0] == key:
                return self._entry[1]
            tts = await build(key)
            self._entry = (key, tts)
            return tts

    def take(self, key: Key) -> TextToSpeech | None:
        """Забирает TTS голоса из кеша (голос становится текущим), иначе None."""
        if self._entry is None or self._entry[0] != key:
            return None
        tts = self._entry[1]
        self._entry = None
        return tts

    def clear(self) -> None:
        """Отпускает закешированный TTS."""
        self._entry = None


async def render_wav(tts: TextToSpeech, key: Key, style: str, text: str) -> bytes:
    """Озвучивает текст и отдаёт WAV; пустой звук — RuntimeError (модель не озвучила)."""
    pcm = b"".join([chunk async for chunk in tts.synthesize(text, style)])
    if not pcm:
        raise RuntimeError(f"Голос {key[0]}/{key[1]} не озвучил образец: модель вернула пустой звук")
    return to_wav(pcm)
