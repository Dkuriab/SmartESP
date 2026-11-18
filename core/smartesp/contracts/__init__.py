"""Договоры ядра: только типы и протоколы, без логики."""

from .audio import SAMPLE_RATE, Utterance
from .control import ChangeResult, ConfigStore, CorePort, Section, VoicePort
from .device import DeviceInfo, DevicePort
from .events import CoreEvent, EventFeed, EventSink, Subscription
from .executor import ChatMessage, Executor, ExecutorError, ReplyPart, Unloads, WarmsUp
from .stage import Analyzer, Annotation, Stage
from .stt import SpeechToText
from .tts import TextToSpeech, VoiceInfo, VoiceNotDownloadedError

__all__ = [
    "SAMPLE_RATE",
    "Analyzer",
    "Annotation",
    "ChangeResult",
    "ChatMessage",
    "ConfigStore",
    "CorePort",
    "CoreEvent",
    "DeviceInfo",
    "DevicePort",
    "EventFeed",
    "EventSink",
    "Executor",
    "ExecutorError",
    "ReplyPart",
    "Section",
    "SpeechToText",
    "Stage",
    "Subscription",
    "TextToSpeech",
    "Unloads",
    "Utterance",
    "VoiceInfo",
    "VoiceNotDownloadedError",
    "VoicePort",
    "WarmsUp",
]
