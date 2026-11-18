"""Модуль синтеза речи (Piper) и подготовка текста и звука для голосов."""

from .pcm import QUIET_VOLUME, float_to_s16, scale_volume
from .piper_tts import PiperTTS
from .resample import resample_s16
from .text_prep import keep_speakable, numbers_to_words

__all__ = [
    "QUIET_VOLUME",
    "PiperTTS",
    "float_to_s16",
    "keep_speakable",
    "numbers_to_words",
    "resample_s16",
    "scale_volume",
]
