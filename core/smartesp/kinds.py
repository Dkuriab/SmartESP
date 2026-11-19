"""Связка: реестры реализаций по полю kind из config.yaml и части из настроек.

Вместе с main.py и wiring.py — единственное место, где модули встречаются: здесь
настройки переводятся в описания для сети исполнителей и обработчиков.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from smartesp.config import Config, ExecutorConfig, StageConfig, SttConfig
from smartesp.contracts import Analyzer, Executor, SpeechToText, Stage, TextToSpeech, ToolBox
from smartesp.network import ExecutorNetwork, MemberSpec, build_network
from smartesp.stages import run_stages
from smartesp.tools import ConnectorSpec


class StartupError(Exception):
    """Ядро не может стартовать: понятное сообщение для человека."""


@dataclass(frozen=True)
class Kinds:
    """Реестры реализаций по полю kind из config.yaml."""

    stt: Mapping[str, Callable[[SttConfig], SpeechToText]]
    tts: Mapping[str, Callable[[Path, str], TextToSpeech]]  # (путь голоса, голос)
    executors: Mapping[str, Callable[[ExecutorConfig], Executor]]
    stages: Mapping[str, Callable[[StageConfig], Stage]]


@dataclass(frozen=True)
class Ollama:
    """Сведения Ollama для status, списка моделей и проверки умения инструментов."""

    models: Callable[[], Awaitable[list[tuple[str, int]]]]
    loaded: Callable[[], Awaitable[list[str]]]
    capabilities: Callable[[str], Awaitable[frozenset[str]]]


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


def kinds_validator(kinds: Kinds) -> Callable[[object], None]:
    """Проверка правки настроек пультом: неизвестный вид — ValueError (правка invalid)."""

    def validate(config: object) -> None:
        try:
            check_kinds(cast(Config, config), kinds)
        except StartupError as error:
            raise ValueError(str(error)) from error

    return validate


def member_specs(config: Config) -> list[MemberSpec]:
    """Исполнители из настроек — описания участников сети."""
    return [
        MemberSpec(
            e.id, e.name, e.description, e.model, e.system_prompt, tuple((d.to, d.when) for d in e.delegates)
        )
        for e in config.executors
    ]


def connector_specs(config: Config) -> list[ConnectorSpec]:
    """Коннекторы из настроек — описания для MCP-хаба («{repo}» — путь к репозиторию)."""
    expanded = [c.expanded() for c in config.connectors]
    return [ConnectorSpec(c.id, c.name, c.command, tuple(c.args), dict(c.env), c.enabled) for c in expanded]


def prompt_stages(config: Config, kinds: Kinds) -> list[Stage]:
    """Обработчики известных видов — только ради их правил в промптах (моделей они не грузят)."""
    return [kinds.stages[s.kind](s) for s in config.stages if s.kind in kinds.stages]


def _maker(config: Config, kinds: Kinds) -> Callable[[str, str], Executor]:
    """make(id, итоговый промпт) — исполнитель из реестра по настройкам исполнителя id."""
    by_id = {e.id: e for e in config.executors}

    def make(executor_id: str, prompt: str) -> Executor:
        executor = by_id[executor_id]
        factory = pick(kinds.executors, executor.kind, "executor")
        return factory(executor.model_copy(update={"system_prompt": prompt}))

    return make


async def build_answering(
    config: Config,
    kinds: Kinds,
    capabilities: Callable[[str], Awaitable[frozenset[str]]],
    toolbox: ToolBox | None = None,
) -> tuple[Analyzer, ExecutorNetwork]:
    """Обработчики и сеть исполнителей из настроек; неизвестный вид — StartupError.

    toolbox — инструменты коннекторов (снимок берётся при сборке).
    """
    stages = [(pick(kinds.stages, s.kind, "stage")(s), s.timeout_ms / 1000) for s in config.stages]
    specs, plain = member_specs(config), [stage for stage, _ in stages]
    network = await build_network(
        config.entry_executor().id, specs, plain, _maker(config, kinds), capabilities, toolbox
    )
    analyze: Analyzer = functools.partial(run_stages, stages)
    return analyze, network
