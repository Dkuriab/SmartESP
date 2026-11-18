"""Модуль обработчиков реплик: запуск всех обработчиков и их реализации."""

from .runner import run_stages
from .whisper_detect import WhisperDetect

__all__ = ["WhisperDetect", "run_stages"]
