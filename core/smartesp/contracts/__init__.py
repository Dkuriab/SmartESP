"""Договоры ядра: только типы и протоколы, без логики."""

from .ask import Answer, AskUnavailable, AudioUndecodable, Question
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
    ModelNotLoadedError,
    ReplyPart,
    ToolCall,
    ToolSpec,
    Unloads,
    UsesModels,
    WarmsUp,
)
from .notify import Announcer, Preempt
from .playback import FilePlayback, PlaybackRefusal, PlaybackRefused
from .stage import Analyzer, Annotation, Stage
from .stt import SpeechToText
from .tools import ConnectorState, ConnectorStateName, ToolBox, ToolObserver, ToolPhase, ToolResult, ToolUse
from .tts import TextToSpeech, VoiceInfo, VoiceNotDownloadedError

__all__ = [
    "DELEGATE_TOOL",
    "SAMPLE_RATE",
    "Analyzer",
    "Announcer",
    "Annotation",
    "Answer",
    "AskUnavailable",
    "AudioUndecodable",
    "ChangeResult",
    "ChatMessage",
    "ConfigStore",
    "ConnectorState",
    "ConnectorStateName",
    "CorePort",
    "CoreEvent",
    "Delivery",
    "DeviceInfo",
    "DevicePort",
    "EventFeed",
    "EventSink",
    "Executor",
    "ExecutorError",
    "FilePlayback",
    "Handoff",
    "Identified",
    "ModelNotLoadedError",
    "PlaybackRefusal",
    "PlaybackRefused",
    "Preempt",
    "Question",
    "ReplyPart",
    "Section",
    "SpeechToText",
    "Stage",
    "Subscription",
    "TextToSpeech",
    "ToolBox",
    "ToolCall",
    "ToolObserver",
    "ToolPhase",
    "ToolResult",
    "ToolSpec",
    "ToolUse",
    "Unloads",
    "UsesModels",
    "Utterance",
    "VoiceInfo",
    "VoiceNotDownloadedError",
    "VoicePort",
    "WarmsUp",
]
