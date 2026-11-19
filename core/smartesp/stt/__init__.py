"""Модуль распознавания речи (mlx-whisper) и разбора звука через ffmpeg (голосовое и файлы)."""

from .decode import decode_audio, decode_file, find_ffmpeg
from .mlx_whisper_stt import MlxWhisperSTT, pcm_to_float

__all__ = ["MlxWhisperSTT", "decode_audio", "decode_file", "find_ffmpeg", "pcm_to_float"]
