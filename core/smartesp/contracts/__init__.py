"""Договоры ядра: только типы и протоколы, без логики."""

from .audio import SAMPLE_RATE, Utterance
from .device import DevicePort
from .executor import ChatMessage, Executor, ExecutorError, ReplyPart
from .stage import Analyzer, Annotation, Stage
from .stt import SpeechToText
from .tts import TextToSpeech, VoiceInfo

__all__ = [
    "SAMPLE_RATE",
    "Analyzer",
    "Annotation",
    "ChatMessage",
    "DevicePort",
    "Executor",
    "ExecutorError",
    "ReplyPart",
    "SpeechToText",
    "Stage",
    "TextToSpeech",
    "Utterance",
    "VoiceInfo",
]
