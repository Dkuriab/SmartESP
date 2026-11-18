"""Синтез речи через Piper."""

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

from piper import PiperVoice

from .resample import resample_s16

_STYLES = ["normal"]
_DONE = object()


class PiperTTS:
    """Озвучка голосом Piper; отдаёт PCM 16 кГц s16le моно."""

    def __init__(self, voice_path: Path) -> None:
        """voice_path: файл .onnx голоса (рядом лежит .onnx.json)."""
        self._voice = PiperVoice.load(voice_path)
        self._lock = threading.Lock()

    def styles(self) -> list[str]:
        """Возвращает имена доступных стилей озвучки."""
        return list(_STYLES)

    async def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        """Озвучивает текст; неизвестный стиль заменяется на normal.

        Синтез идёт в потоке, куски (по предложению) отдаются по мере готовности.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()
        worker = asyncio.create_task(asyncio.to_thread(self._run, text, loop, queue))
        try:
            while (item := await queue.get()) is not _DONE:
                if isinstance(item, BaseException):
                    raise item
                assert isinstance(item, bytes)
                yield item
        finally:
            await worker

    def _run(self, text: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[object]) -> None:
        """Рабочий поток: синтезирует и кладёт ресемплированные куски в очередь."""
        try:
            with self._lock:
                for chunk in self._voice.synthesize(text):
                    pcm = resample_s16(chunk.audio_int16_bytes, chunk.sample_rate)
                    loop.call_soon_threadsafe(queue.put_nowait, pcm)
        except Exception as error:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, error)
        loop.call_soon_threadsafe(queue.put_nowait, _DONE)
