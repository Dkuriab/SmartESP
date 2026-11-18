"""Модуль синтеза речи (Piper)."""

from .piper_tts import PiperTTS
from .resample import resample_s16

__all__ = ["PiperTTS", "resample_s16"]
