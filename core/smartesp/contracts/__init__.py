"""Договоры ядра: только типы и протоколы, без логики."""

from .audio import SAMPLE_RATE, Utterance
from .control import ChangeResult, ConfigStore, CorePort, Section, VoicePort
from .device import Delivery, DeviceInfo, DevicePort
from .events import CoreEvent, EventFeed, EventSink, Subscription
from .executor import (
    DELEGATE_TOOL,
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
    "DELEGATE_TOOL",
    "SAMPLE_RATE",
    "Analyzer",
    "Annotation",
    "ChangeResult",
    "ChatMessage",
    "ConfigStore",
    "CorePort",
    "CoreEvent",
    "Delivery",
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
