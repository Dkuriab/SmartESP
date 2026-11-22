"""Модуль людей: реестр людей дома, образцы голоса и узнавание того, кто говорит."""

from .encoder import OnnxVoicePrint
from .matching import MARGIN, THRESHOLD
from .model import MODEL_ID, ModelDownloadError, download_model, model_path
from .service import People

__all__ = [
    "MARGIN",
    "MODEL_ID",
    "THRESHOLD",
    "ModelDownloadError",
    "OnnxVoicePrint",
    "People",
    "download_model",
    "model_path",
]
