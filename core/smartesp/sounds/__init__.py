"""Свои звуки сигналов колонки: библиотека в папке данных, подготовка (numpy), доставка по воздуху."""

from .prepare import prepare_sound, to_wav
from .service import Sounds

__all__ = ["Sounds", "prepare_sound", "to_wav"]
