"""Реестры реализаций по полю kind из config.yaml и проверка видов до старта."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from smartesp.config import Config, ExecutorConfig, StageConfig, SttConfig
from smartesp.contracts import Executor, SpeechToText, Stage, TextToSpeech


class StartupError(Exception):
    """Ядро не может стартовать: понятное сообщение для человека."""


@dataclass(frozen=True)
class Kinds:
    """Реестры реализаций по полю kind из config.yaml."""

    stt: Mapping[str, Callable[[SttConfig], SpeechToText]]
    tts: Mapping[str, Callable[[Path, str], TextToSpeech]]  # (путь голоса, голос)
    executors: Mapping[str, Callable[[ExecutorConfig], Executor]]
    stages: Mapping[str, Callable[[StageConfig], Stage]]


def pick[T](registry: Mapping[str, T], kind: str, what: str) -> T:
    """Реализация из реестра по имени; неизвестное имя — StartupError со списком известных."""
    if kind not in registry:
        known = ", ".join(sorted(registry)) or "нет"
        raise StartupError(f"Неизвестный {what} kind={kind!r}; известные: {known}")
    return registry[kind]


def check_kinds(config: Config, kinds: Kinds) -> None:
    """Проверяет виды stt, tts, всех исполнителей и обработчиков до старта сервера."""
    pick(kinds.stt, config.stt.kind, "stt")
    pick(kinds.tts, config.tts.kind, "tts")
    for executor in config.executors:
        pick(kinds.executors, executor.kind, "executor")
    for stage in config.stages:
        pick(kinds.stages, stage.kind, "stage")
