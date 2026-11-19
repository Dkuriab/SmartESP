"""Сборка сети из описаний участников: цели связей, итоговые промпты и умение инструментов."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from smartesp.contracts import Executor, Stage, UsesModels

from .network import ExecutorNetwork, Member
from .rules import Target, delegate_rule

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


def _prompt(spec: MemberSpec, stages: Sequence[Stage], targets: Sequence[Target], tools_ok: bool) -> str:
    """Итоговый промпт: свой + правила обработчиков + правило передачи, если модель умеет инструменты."""
    prompt = with_stage_hints(spec.system_prompt, stages)
    rule = delegate_rule(targets) if tools_ok else ""
    return "\n".join([prompt, rule]) if rule else prompt


def member_prompts(
    specs: Sequence[MemberSpec], stages: Sequence[Stage], tools_ok: Mapping[str, bool]
) -> dict[str, str]:
    """Итоговые промпты участников по id; нет в tools_ok — модель считается без инструментов."""
    return {s.id: _prompt(s, stages, active_targets(s, specs), tools_ok.get(s.id, False)) for s in specs}


async def _tools_ok_by_id(specs: Sequence[MemberSpec], capabilities: Capabilities) -> dict[str, bool]:
    """Умеет ли модель каждого участника инструменты; каждая модель спрашивается один раз."""
    models = list(dict.fromkeys(s.model for s in specs))
    found = await asyncio.gather(*(capabilities(model) for model in models))
    tools = {model: TOOLS in caps for model, caps in zip(models, found, strict=True)}
    return {s.id: tools[s.model] for s in specs}


async def build_network(
    entry_id: str,
    specs: Sequence[MemberSpec],
    stages: Sequence[Stage],
    make: Callable[[str, str], Executor],
    capabilities: Capabilities,
) -> ExecutorNetwork:
    """Сеть из описаний; модели не греются.

    make(id, итоговый промпт) — исполнитель участника. Промпт каждого: свой +
    правила обработчиков + правило передачи его целям, если модель умеет
    инструменты (capabilities(модель) содержит tools).

    Участник, до которого доходят только на глубине max_depth, получает правило
    в промпт, но инструмента у него на этой глубине нет: промпт один на все глубины.
    """
    tools_ok = await _tools_ok_by_id(specs, capabilities)
    members: dict[str, Member] = {}
    for spec in specs:
        targets = active_targets(spec, specs)
        executor = make(spec.id, _prompt(spec, stages, targets, tools_ok[spec.id]))
        members[spec.id] = Member(executor, spec.name, targets, tools_ok[spec.id])
    return ExecutorNetwork(entry_id, members)


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
    ) -> None:
        """entry() — id входного; specs(), stages() — из текущих настроек; live() — живой исполнитель."""
        self._entry = entry
        self._specs = specs
        self._stages = stages
        self._known = known
        self._live = live

    def all(self) -> dict[str, str]:
        """Итоговые промпты всех участников по id."""
        specs = self._specs()
        return member_prompts(specs, self._stages(), {s.id: self._tools_ok(s) for s in specs})

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
