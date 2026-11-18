"""Пульт ядра: состояние, очередь изменений настроек и сводка status."""

from .changes import RESTART_SECTIONS
from .core import Core

__all__ = ["RESTART_SECTIONS", "Core"]
