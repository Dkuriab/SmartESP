"""Сеть исполнителей из настроек: цели связей, итоговые промпты и умение инструментов.

Перевод настроек в участников сети — логика, поэтому она здесь, а не в wiring.py.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Mapping, Sequence

from smartesp.config import Config, ExecutorConfig
from smartesp.contracts import Analyzer, Stage
from smartesp.network import ExecutorNetwork, Member, Target, delegate_rule
from smartesp.stages import run_stages

from .capabilities import TOOLS, CapabilityCache
from .kinds import Kinds, pick

Capabilities = Callable[[str], Awaitable[frozenset[str]]]  # модель → её возможности


def with_stage_hints(prompt: str, stages: Sequence[Stage]) -> str:
    """Системный промпт исполнителя + правила включённых обработчиков."""
    hints = [stage.prompt_hint for stage in stages if stage.prompt_hint]
    return "\n".join([prompt, *hints])


def active_targets(executor: ExecutorConfig, config: Config) -> tuple[Target, ...]:
    """Активные цели связей исполнителя.

    Условие связи — when, а если оно пустое — описание цели. Связь без того и
    другого неактивна и отбрасывается; связь на несуществующего — тоже.
    """
    by_id = {e.id: e for e in config.executors}
    targets: list[Target] = []
    for link in executor.delegates:
        target = by_id.get(link.to)
        if target is None:
            continue
        when = link.when.strip() or target.description.strip()
        if when:
            targets.append(Target(target.id, target.name, when))
    return tuple(targets)


def _prompt(
    executor: ExecutorConfig, stages: Sequence[Stage], targets: Sequence[Target], tools_ok: bool
) -> str:
    """Итоговый промпт: свой + правила обработчиков + правило передачи, если модель умеет инструменты."""
    prompt = with_stage_hints(executor.system_prompt, stages)
    rule = delegate_rule(targets) if tools_ok else ""
    return "\n".join([prompt, rule]) if rule else prompt


def _prompt_stages(config: Config, kinds: Kinds) -> list[Stage]:
    """Обработчики известных видов — только ради их правил (моделей они не грузят)."""
    return [kinds.stages[s.kind](s) for s in config.stages if s.kind in kinds.stages]


def executor_prompts(config: Config, kinds: Kinds, tools_ok_by_id: Mapping[str, bool]) -> dict[str, str]:
    """Итоговые промпты исполнителей по id; нет в tools_ok_by_id — модель считается без инструментов."""
    stages = _prompt_stages(config, kinds)
    return {
        e.id: _prompt(e, stages, active_targets(e, config), tools_ok_by_id.get(e.id, False))
        for e in config.executors
    }


async def _tools_ok_by_id(config: Config, capabilities: Capabilities) -> dict[str, bool]:
    """Умеет ли модель каждого исполнителя инструменты; каждая модель спрашивается один раз."""
    models = list(dict.fromkeys(e.model for e in config.executors))
    found = await asyncio.gather(*(capabilities(model) for model in models))
    tools = {model: TOOLS in caps for model, caps in zip(models, found, strict=True)}
    return {e.id: tools[e.model] for e in config.executors}


async def build_network(
    config: Config, kinds: Kinds, capabilities: Capabilities
) -> tuple[Analyzer, ExecutorNetwork]:
    """Обработчики и сеть исполнителей из настроек; модели не греются.

    Промпт каждого: свой + правила обработчиков + правило передачи его целям,
    если модель умеет инструменты (capabilities(модель) содержит tools).
    Неизвестный вид исполнителя или обработчика — StartupError.
    """
    stages = [(pick(kinds.stages, s.kind, "stage")(s), s.timeout_ms / 1000) for s in config.stages]
    plain = [stage for stage, _ in stages]
    tools_ok = await _tools_ok_by_id(config, capabilities)
    members: dict[str, Member] = {}
    for executor in config.executors:
        make = pick(kinds.executors, executor.kind, "executor")
        targets = active_targets(executor, config)
        prompt = _prompt(executor, plain, targets, tools_ok[executor.id])
        built = make(executor.model_copy(update={"system_prompt": prompt}))
        members[executor.id] = Member(built, executor.name, targets, tools_ok[executor.id])
    analyze: Analyzer = functools.partial(run_stages, stages)
    return analyze, ExecutorNetwork(config.entry_executor().id, members)


class NetworkPrompts:
    """Итоговые промпты для интерфейса: из текущих настроек и уже известных возможностей моделей."""

    def __init__(self, config: Callable[[], Config], kinds: Kinds, capabilities: CapabilityCache) -> None:
        """config() — текущие настройки; capabilities — кеш, который наполняет сборка сети."""
        self._config = config
        self._kinds = kinds
        self._capabilities = capabilities

    def all(self) -> dict[str, str]:
        """Итоговые промпты всех исполнителей по id."""
        return self._prompts(self._config())

    def entry(self) -> str:
        """Итоговый промпт входного исполнителя."""
        config = self._config()
        return self._prompts(config)[config.entry_executor().id]

    def _prompts(self, config: Config) -> dict[str, str]:
        tools_ok = {e.id: TOOLS in self._capabilities.known(e.model) for e in config.executors}
        return executor_prompts(config, self._kinds, tools_ok)
