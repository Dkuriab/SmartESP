"""Синтез речи через Vosk TTS (русская многоголосая модель)."""

import asyncio
import json
import logging
import threading
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .pcm import QUIET_VOLUME, scale_volume
from .resample import resample_s16
from .text_prep import keep_speakable, numbers_to_words

_log = logging.getLogger(__name__)

_STYLES = ["normal", "quiet"]
# Скорость речи тихого стиля: меньше 1.0 — медленнее.
_QUIET_SPEECH_RATE = 0.87


class VoskTTS:
    """Озвучка голосом Vosk; отдаёт PCM 16 кГц s16le моно."""

    def __init__(self, model_dir: Path, speaker: str) -> None:
        """model_dir: папка модели с config.json; speaker: ключ speaker_id_map (female_0 ...)."""
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        speakers: dict[str, int] = config["speaker_id_map"]
        if speaker not in speakers:
            raise ValueError(f"Неизвестный голос Vosk {speaker!r}; доступны: {', '.join(speakers)}")
        self._speaker_id = speakers[speaker]
        self._rate = int(config["audio"]["sample_rate"])
        self._synth = self._load(model_dir)
        self._lock = threading.Lock()

    @staticmethod
    def _load(model_dir: Path) -> Any:
        """Загружает модель Vosk и создаёт синтезатор."""
        # vosk_tts при первой компиляции сыплет SyntaxWarning из-за своих regexp.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=SyntaxWarning)
            from vosk_tts import Model, Synth

        return Synth(Model(model_path=str(model_dir)))

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
            kwargs: dict[str, Any] = {"speaker_id": self._speaker_id}
            if quiet:
                kwargs["speech_rate"] = _QUIET_SPEECH_RATE
            with self._lock:
                audio = self._synth.synth_audio(text, **kwargs)
            pcm = resample_s16(audio.astype("<i2").tobytes(), self._rate)
            return scale_volume(pcm, QUIET_VOLUME) if quiet else pcm
        except Exception:  # noqa: BLE001
            _log.error("Vosk: синтез не удался для %r", text, exc_info=True)
            return b""
