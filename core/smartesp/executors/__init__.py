"""Модуль исполнителей: Ollama и LM Studio на Mac, облачный сервис с OpenAI-совместимым API."""

from .cloud_executor import CloudExecutor
from .cloud_models import CloudCatalog, with_cloud
from .lmstudio_executor import LmStudioExecutor
from .ollama_executor import OllamaExecutor
from .ollama_models import list_models, loaded_models, model_capabilities, unload_model

__all__ = [
    "CloudCatalog",
    "CloudExecutor",
    "LmStudioExecutor",
    "OllamaExecutor",
    "list_models",
    "loaded_models",
    "model_capabilities",
    "unload_model",
    "with_cloud",
]
