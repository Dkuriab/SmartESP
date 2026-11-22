"""Модуль обработчиков реплик: запуск всех обработчиков и их реализации."""

from .clock import Clock
from .people import PEOPLE_VOICES, PeopleStage
from .runner import run_stages
from .system_state import SYSTEM_FACTS, SystemSnapshot, SystemState
from .whisper_detect import WhisperDetect

__all__ = [
    "PEOPLE_VOICES",
    "SYSTEM_FACTS",
    "Clock",
    "PeopleStage",
    "SystemSnapshot",
    "SystemState",
    "WhisperDetect",
    "run_stages",
]
