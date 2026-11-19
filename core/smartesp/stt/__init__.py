"""Модуль распознавания речи (mlx-whisper) и разбора звука для него (ffmpeg)."""

from .decode import decode_audio, find_ffmpeg
from .mlx_whisper_stt import MlxWhisperSTT, pcm_to_float

__all__ = ["MlxWhisperSTT", "decode_audio", "find_ffmpeg", "pcm_to_float"]
