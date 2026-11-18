"""Модуль исполнителей (Ollama)."""

from .ollama_executor import OllamaExecutor
from .ollama_models import list_models, loaded_models

__all__ = ["OllamaExecutor", "list_models", "loaded_models"]
