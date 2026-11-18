"""Синтез речи через Silero v5 (русские голоса)."""

import asyncio
import logging
import threading
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .pcm import QUIET_VOLUME, float_to_s16, scale_volume
from .resample import resample_s16
from .text_prep import keep_speakable, numbers_to_words

_log = logging.getLogger(__name__)

_STYLES = ["normal", "quiet"]
# Частота, на которой Silero отдаёт звук до ресемплинга.
_MODEL_RATE = 24000


class SileroTTS:
    """Озвучка голосом Silero v5; отдаёт PCM 16 кГц s16le моно."""

    def __init__(self, model_path: Path, speaker: str) -> None:
        """model_path: файл v5_ru.pt; speaker: имя голоса (например, xenia)."""
        self._model = self._load(model_path)
        self._speaker = speaker
        self._lock = threading.Lock()

    @staticmethod
    def _load(path: Path) -> Any:
        """Загружает модель из пакета torch.package на CPU."""
        import torch
        from torch.package.package_importer import PackageImporter

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, module=r"torch\.package.*")
            importer = PackageImporter(str(path))
            model = importer.load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        return model

    def styles(self) -> list[str]:
        """Возвращает имена доступных стилей озвучки."""
        return list(_STYLES)

    async def warm_up(self) -> None:
        """Прогревает модель: синтезирует короткую фразу и выбрасывает результат."""
        async for _ in self.synthesize("Привет.", "normal"):
            pass

    async def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        """Озвучивает текст одним куском; неизвестный стиль заменяется на normal.

        Пустой итератор — нечего говорить или синтез не удался (ошибка в журнале).
        """
        clean = keep_speakable(numbers_to_words(text))
        if not clean:
            return
        pcm = await asyncio.to_thread(self._render, clean, style == "quiet")
        if pcm:
            yield pcm

    def _render(self, text: str, quiet: bool) -> bytes:
        """Рабочий поток: синтез под замком; при ошибке пишет в журнал и отдаёт b''."""
        try:
            with self._lock:
                if quiet:
                    ssml = f'<speak><prosody rate="slow">{text}</prosody></speak>'
                    audio = self._model.apply_tts(
                        ssml_text=ssml, speaker=self._speaker, sample_rate=_MODEL_RATE
                    )
                else:
                    audio = self._model.apply_tts(text=text, speaker=self._speaker, sample_rate=_MODEL_RATE)
            pcm = resample_s16(float_to_s16(audio.numpy()), _MODEL_RATE)
        except Exception:  # noqa: BLE001
            _log.error("Silero: синтез не удался для %r", text, exc_info=True)
            return b""
        return scale_volume(pcm, QUIET_VOLUME) if quiet else pcm
