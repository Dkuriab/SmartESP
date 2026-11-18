"""Распознавание речи через mlx-whisper."""

import asyncio
import threading

import numpy as np


def pcm_to_float(pcm: bytes) -> np.ndarray:
    """Переводит PCM s16le в float32 в диапазоне [-1, 1)."""
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class MlxWhisperSTT:
    """Распознаватель речи на mlx-whisper (реализует SpeechToText)."""

    def __init__(self, model: str, language: str) -> None:
        """model — репозиторий Hugging Face или путь; language — код языка («ru»)."""
        self._model = model
        self._language = language
        # mlx не потокобезопасен: распознавания идут строго по одному
        self._lock = threading.Lock()

    def _run(self, audio: np.ndarray) -> str:
        # Импорт внутри: тяжёлый, и тесты без модели его не требуют
        import mlx_whisper

        with self._lock:
            result = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self._model,
                language=self._language,
                # Короткие реплики: без контекста предыдущего текста и без
                # случайной выборки — меньше зацикливаний и галлюцинаций
                condition_on_previous_text=False,
                temperature=0.0,
            )
        return str(result["text"]).strip()

    async def transcribe(self, pcm: bytes) -> str:
        """Распознаёт PCM 16 кГц s16le mono; пустой вход даёт пустую строку."""
        if not pcm:
            return ""
        return await asyncio.to_thread(self._run, pcm_to_float(pcm))
