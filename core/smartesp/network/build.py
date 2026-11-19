"""Сборка сети из описаний участников: цели связей, итоговые промпты и умение инструментов."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from smartesp.contracts import Executor, Stage, ToolBox, ToolObserver, UsesModels

from .network import ExecutorNetwork, Member
from .rules import TOOLS_RULE, Target, delegate_rule

TOOLS = "tools"  # возможность модели вызывать инструменты
Capabilities = Callable[[str], Awaitable[frozenset[str]]]  # модель → её возможности


@dataclass(frozen=True)
class MemberSpec:
    """Описание участника из настроек.

    links — связи (id цели, when); пустой when заменяется описанием цели.
    """

    id: str
    name: str
    description: str
    model: str
    system_prompt: str
    links: tuple[tuple[str, str], ...] = ()


def with_stage_hints(prompt: str, stages: Sequence[Stage]) -> str:
    """Системный промпт исполнителя + правила включённых обработчиков."""
    hints = [stage.prompt_hint for stage in stages if stage.prompt_hint]
    return "\n".join([prompt, *hints])


def active_targets(spec: MemberSpec, specs: Sequence[MemberSpec]) -> tuple[Target, ...]:
    """Активные цели связей участника.

    Условие связи — when, а если оно пустое — описание цели. Связь без того и
    другого неактивна и отбрасывается; связь на несуществующего — тоже.
    """
    by_id = {s.id: s for s in specs}
    targets: list[Target] = []
    for target_id, when in spec.links:
        target = by_id.get(target_id)
        if target is None:
            continue
        condition = when.strip() or target.description.strip()
        if condition:
            targets.append(Target(target.id, target.name, condition))
    return tuple(targets)


def _prompt(
    spec: MemberSpec,
    stages: Sequence[Stage],
    targets: Sequence[Target],
    tools_ok: bool,
    has_tools: bool = False,
    delegate: bool = True,
) -> str:
    """Итоговый промпт: свой + правила обработчиков + правила передачи и инструментов (если умеет)."""
    prompt = with_stage_hints(spec.system_prompt, stages)
    rules = [delegate_rule(targets)] if tools_ok and delegate else []
    if tools_ok and has_tools:
        rules.append(TOOLS_RULE)
    return "\n".join([prompt, *(r for r in rules if r)])


def member_prompts(
    specs: Sequence[MemberSpec],
    stages: Sequence[Stage],
    tools_ok: Mapping[str, bool],
    has_tools: bool = False,
) -> dict[str, str]:
    """Итоговые промпты участников по id; нет в tools_ok — модель считается без инструментов.

    has_tools — у сети есть инструменты коннекторов (тогда добавляется правило про факты).
    """
    return {
        s.id: _prompt(s, stages, active_targets(s, specs), tools_ok.get(s.id, False), has_tools)
        for s in specs
    }


async def _capabilities_by_model(
    specs: Sequence[MemberSpec], capabilities: Capabilities
) -> dict[str, frozenset[str]]:
    """Возможности модели каждого участника; каждая модель спрашивается один раз."""
    models = list(dict.fromkeys(s.model for s in specs))
    found = await asyncio.gather(*(capabilities(model) for model in models))
    return dict(zip(models, found, strict=True))


async def build_network(
    entry_id: str,
    specs: Sequence[MemberSpec],
    stages: Sequence[Stage],
    make: Callable[[str, str], Executor],
    capabilities: Capabilities,
    toolbox: ToolBox | None = None,
    on_tool: ToolObserver | None = None,
) -> ExecutorNetwork:
    """Сеть из описаний; модели не греются.

    make(id, итоговый промпт) — исполнитель участника. Промпт каждого: свой +
    правила обработчиков + правило передачи его целям, если модель умеет
    инструменты (capabilities(модель) содержит tools).

    Участнику с правилом передачи собирается и вариант plain (та же модель,
    промпт без правила): на глубине max_depth инструмента у него нет, и правило
    только заставило бы его обещать передачу. Модели, чьи возможности узнать не
    удалось (пустой ответ), сеть помнит в unknown_models.

    toolbox — инструменты коннекторов: участники, чья модель умеет инструменты,
    получают toolbox.specs() (снимок на момент сборки) вместе с delegate.
    on_tool — получает начало и конец каждого вызова инструмента (для живой подсветки).
    """
    found = await _capabilities_by_model(specs, capabilities)
    tools = tuple(toolbox.specs()) if toolbox is not None else ()
    members: dict[str, Member] = {}
    for spec in specs:
        tools_ok = TOOLS in found[spec.model]
        targets = active_targets(spec, specs)
        executor = make(spec.id, _prompt(spec, stages, targets, tools_ok, bool(tools)))
        plain = (
            make(spec.id, _prompt(spec, stages, targets, tools_ok, bool(tools), False))
            if tools_ok and targets
            else None
        )
        own_tools = tools if tools_ok else ()
        members[spec.id] = Member(executor, spec.name, targets, tools_ok, plain, own_tools)
    unknown = frozenset(model for model, caps in found.items() if not caps)
    return ExecutorNetwork(entry_id, members, unknown=unknown, toolbox=toolbox, on_tool=on_tool)


class NetworkPrompts:
    """Итоговые промпты для интерфейса: из текущих настроек.

    Умение инструментов берётся у живой сети, если в ней есть участник с тем же id
    и той же моделью; иначе — из уже известных возможностей модели (known).
    """

    def __init__(
        self,
        entry: Callable[[], str],
        specs: Callable[[], Sequence[MemberSpec]],
        stages: Callable[[], Sequence[Stage]],
        known: Callable[[str], frozenset[str]],
        live: Callable[[], object] = lambda: None,
        has_tools: Callable[[], bool] = lambda: False,
    ) -> None:
        """entry() — id входного; specs(), stages() — из текущих настроек; live() — живой исполнитель.

        has_tools() — есть ли сейчас инструменты коннекторов.
        """
        self._has_tools = has_tools
        self._entry = entry
        self._specs = specs
        self._stages = stages
        self._known = known
        self._live = live

    def all(self) -> dict[str, str]:
        """Итоговые промпты всех участников по id."""
        specs = self._specs()
        return member_prompts(
            specs, self._stages(), {s.id: self._tools_ok(s) for s in specs}, self._has_tools()
        )

    def entry(self) -> str:
        """Итоговый промпт входного исполнителя."""
        return self.all()[self._entry()]

    def _tools_ok(self, spec: MemberSpec) -> bool:
        live = self._live()
        member = live.members.get(spec.id) if isinstance(live, ExecutorNetwork) else None
        if member is not None and isinstance(member.executor, UsesModels):
            if spec.model in member.executor.models():
                return member.tools_ok
        return TOOLS in self._known(spec.model)
