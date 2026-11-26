"""Потоки звука на колонках: очередь источников (файл или ссылка), пауза, громкость — без музыки."""

from .capture import CAPTURE_PREFIX, capture_probe, input_names
from .runner import PATH
from .service import Streams
from .sources import ffmpeg_decoder

__all__ = ["CAPTURE_PREFIX", "PATH", "Streams", "capture_probe", "ffmpeg_decoder", "input_names"]
