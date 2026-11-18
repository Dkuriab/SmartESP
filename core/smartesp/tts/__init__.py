"""Модуль синтеза речи (Piper) и подготовка текста и звука для голосов."""

from .catalog import catalog, is_downloaded, voice_path
from .download import (
    VoiceDownloadError,
    VoiceUnavailableError,
    download_voice,
    ensure_voice,
)
from .pcm import QUIET_VOLUME, float_to_s16, scale_volume
from .piper_tts import PiperTTS
from .resample import resample_s16
from .text_prep import keep_speakable, numbers_to_words

__all__ = [
    "QUIET_VOLUME",
    "PiperTTS",
    "VoiceDownloadError",
    "VoiceUnavailableError",
    "catalog",
    "download_voice",
    "ensure_voice",
    "float_to_s16",
    "is_downloaded",
    "keep_speakable",
    "numbers_to_words",
    "resample_s16",
    "scale_volume",
    "voice_path",
]
