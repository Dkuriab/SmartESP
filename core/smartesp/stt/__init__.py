"""Модуль распознавания речи (mlx-whisper)."""

from .mlx_whisper_stt import MlxWhisperSTT, pcm_to_float

__all__ = ["MlxWhisperSTT", "pcm_to_float"]
