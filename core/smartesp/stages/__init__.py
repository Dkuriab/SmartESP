"""Модуль обработчиков реплик: запуск всех обработчиков и их реализации."""

from .clock import Clock
from .runner import run_stages
from .whisper_detect import WhisperDetect

__all__ = ["Clock", "WhisperDetect", "run_stages"]
