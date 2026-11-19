"""Договоры ядра: только типы и протоколы, без логики."""

from .audio import SAMPLE_RATE, Utterance
from .control import ChangeResult, ConfigStore, CorePort, Section, VoicePort
from .device import DeviceInfo, DevicePort
from .events import CoreEvent, EventFeed, EventSink, Subscription
from .executor import (
    ChatMessage,
    Executor,
    ExecutorError,
    Handoff,
    Identified,
    ReplyPart,
    ToolCall,
    ToolSpec,
    Unloads,
    UsesModels,
    WarmsUp,
)
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
    "Handoff",
    "Identified",
    "ReplyPart",
    "Section",
    "SpeechToText",
    "Stage",
    "Subscription",
    "TextToSpeech",
    "ToolCall",
    "ToolSpec",
    "Unloads",
    "UsesModels",
    "Utterance",
    "VoiceInfo",
    "VoiceNotDownloadedError",
    "VoicePort",
    "WarmsUp",
]
