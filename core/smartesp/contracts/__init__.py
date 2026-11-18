"""Договоры ядра: только типы и протоколы, без логики."""

from .audio import SAMPLE_RATE, Utterance
from .device import DevicePort
from .events import CoreEvent, EventFeed, EventSink, Subscription
from .executor import ChatMessage, Executor, ExecutorError, ReplyPart
from .stage import Analyzer, Annotation, Stage
from .stt import SpeechToText
from .tts import TextToSpeech, VoiceInfo

__all__ = [
    "SAMPLE_RATE",
    "Analyzer",
    "Annotation",
    "ChatMessage",
    "CoreEvent",
    "DevicePort",
    "EventFeed",
    "EventSink",
    "Executor",
    "ExecutorError",
    "ReplyPart",
    "SpeechToText",
    "Stage",
    "Subscription",
    "TextToSpeech",
    "Utterance",
    "VoiceInfo",
]
