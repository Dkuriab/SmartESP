"""Отпечаток голоса моделью ONNX (договор VoicePrint): PCM → вектор единичной длины."""

import threading
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort

from .features import normalized_fbank
from .model import MODEL_ID

THREADS = 4  # потоков onnxruntime: ~15 мс на фразу 2 с против ~35 мс в одном потоке


class OnnxVoicePrint:
    """Модель 3D-Speaker CAM++: вход — fbank с вычтенным средним, выход — 192 числа.

    Сессия загружается при первом отпечатке под замком (прогрев — отпечаток тишины); run у onnxruntime
    потокобезопасен, поэтому отпечатки можно считать из нескольких потоков пула.
    """

    model = MODEL_ID

    def __init__(self, path: Path) -> None:
        """path — файл .onnx (должен существовать к первому отпечатку)."""
        self._path = path
        self._lock = threading.Lock()
        self._session: Any = None

    def _load(self) -> Any:
        with self._lock:
            if self._session is None:
                options = ort.SessionOptions()
                options.intra_op_num_threads = THREADS
                self._session = ort.InferenceSession(
                    str(self._path), options, providers=["CPUExecutionProvider"]
                )
            return self._session

    def embed(self, pcm: bytes) -> list[float]:
        """Отпечаток фразы; звук короче одного кадра (25 мс) — ValueError."""
        feats = normalized_fbank(pcm)
        if len(feats) == 0:
            raise ValueError("слишком короткий звук для отпечатка")
        session = self._load()
        name = session.get_inputs()[0].name
        vector = np.asarray(session.run(None, {name: feats[None]})[0][0], dtype=np.float64)
        norm = float(np.linalg.norm(vector))
        return (vector / norm if norm > 0 else vector).tolist()
