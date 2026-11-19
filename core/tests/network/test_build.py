"""Сборка сети из описаний участников: цели, промпты, умение инструментов."""

from __future__ import annotations

from fakes.fake_executor import FakeOllama
from smartesp.contracts import Annotation, Executor, Utterance
from smartesp.network import (
    MemberSpec,
    NetworkPrompts,
    Target,
    active_targets,
    build_network,
    delegate_rule,
    member_prompts,
    with_stage_hints,
)

HINT = "Пометка [style:quiet] — отвечай тише."


class HintStage:
    """Обработчик-подделка: только правило для промпта."""

    name = "hint"
    prompt_hint = HINT

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        return []


class Made:
    """make(id, промпт): запоминает каждый собранный FakeOllama по id."""

    def __init__(self, models: dict[str, str]) -> None:
        self.models = models
        self.by_id: dict[str, FakeOllama] = {}

    def __call__(self, member_id: str, prompt: str) -> Executor:
        self.by_id[member_id] = FakeOllama([], self.models[member_id], prompt=prompt)
        return self.by_id[member_id]


class Capabilities:
    """Поддельный model_capabilities: по модели — набор возможностей, плюс счёт вызовов."""

    def __init__(self, by_model: dict[str, frozenset[str]] | None = None) -> None:
        self.by_model = by_model or {}
        self.calls: list[str] = []

    async def __call__(self, model: str) -> frozenset[str]:
        self.calls.append(model)
        return self.by_model.get(model, frozenset({"completion", "tools"}))


def specs(when: str = "", description: str = "", big_model: str = "big") -> list[MemberSpec]:
    entry = MemberSpec("dispatcher", "Диспетчер", "", "small", "Промпт диспетчера.", (("big", when),))
    big = MemberSpec("big", "Большая модель", description, big_model, "Промпт big.")
    return [entry, big]


def made_for(items: list[MemberSpec]) -> Made:
    return Made({s.id: s.model for s in items})


async def test_entry_gets_target_and_rule_at_end_of_prompt() -> None:
    items = specs(when="сложное")
    made = made_for(items)
    network = await build_network("dispatcher", items, [HintStage()], made, Capabilities())
    target = Target("big", "Большая модель", "сложное")
    entry = network.members["dispatcher"]
    assert network.id == "dispatcher" and list(network.members) == ["dispatcher", "big"]
    assert entry.targets == (target,) and entry.tools_ok and entry.name == "Диспетчер"
    assert entry.executor is made.by_id["dispatcher"]
    prompt = made.by_id["dispatcher"].prompt
    assert prompt.startswith("Промпт диспетчера.\n" + HINT) and prompt.endswith(delegate_rule([target]))
    assert network.members["big"].targets == () and "delegate" not in made.by_id["big"].prompt


async def test_model_without_tools_gets_no_rule() -> None:
    items = specs(when="сложное")
    made = made_for(items)
    capabilities = Capabilities({"small": frozenset({"completion"})})
    network = await build_network("dispatcher", items, [], made, capabilities)
    assert not network.members["dispatcher"].tools_ok and network.members["big"].tools_ok
    assert made.by_id["dispatcher"].prompt == "Промпт диспетчера."


def test_link_without_when_and_description_is_dropped() -> None:
    items = specs()
    assert active_targets(items[0], items) == ()


def test_empty_when_takes_target_description_and_unknown_target_is_dropped() -> None:
    items = specs(description="рассуждения")
    entry = MemberSpec("dispatcher", "Д", "", "small", "", (("big", " "), ("nobody", "всегда")))
    assert active_targets(entry, [entry, items[1]]) == (Target("big", "Большая модель", "рассуждения"),)


async def test_target_prompt_includes_stage_hints() -> None:
    made = made_for(specs(when="сложное"))
    await build_network("dispatcher", specs(when="сложное"), [HintStage()], made, Capabilities())
    assert made.by_id["big"].prompt == "Промпт big.\n" + HINT


async def test_capabilities_asked_once_per_model() -> None:
    capabilities = Capabilities()
    items = specs(big_model="small")
    await build_network("dispatcher", items, [], made_for(items), capabilities)
    assert capabilities.calls == ["small"]


async def test_member_prompts_match_built_prompts() -> None:
    items = specs(when="сложное")
    made = made_for(items)
    await build_network("dispatcher", items, [HintStage()], made, Capabilities({"big": frozenset()}))
    prompts = member_prompts(items, [HintStage()], {"dispatcher": True, "big": False})
    assert prompts == {"dispatcher": made.by_id["dispatcher"].prompt, "big": made.by_id["big"].prompt}
    assert all("delegate" not in p for p in member_prompts(items, [], {}).values())


async def test_network_prompts_prefer_live_network_then_known() -> None:
    items = specs(when="сложное")
    known: dict[str, frozenset[str]] = {}
    live: list[object] = [None]
    prompts = NetworkPrompts(
        lambda: "dispatcher", lambda: items, list, lambda m: known.get(m, frozenset()), lambda: live[0]
    )
    assert "delegate" not in prompts.entry()  # возможности ещё не известны
    known["small"] = frozenset({"tools"})
    assert "delegate" in prompts.entry() and prompts.entry() == prompts.all()["dispatcher"]
    live[0] = await build_network(
        "dispatcher", items, [], made_for(items), Capabilities({"small": frozenset()})
    )
    assert "delegate" not in prompts.entry()  # живая сеть знает: модель без инструментов
    other = [MemberSpec("dispatcher", "Д", "", "other", "П.", (("big", "x"),)), items[1]]
    prompts = NetworkPrompts(
        lambda: "dispatcher", lambda: other, list, lambda m: frozenset({"tools"}), lambda: live[0]
    )
    assert "delegate" in prompts.entry()  # у живой сети другая модель — берём known


def test_stage_hint_is_appended() -> None:
    assert with_stage_hints("Промпт.", [HintStage()]) == "Промпт.\n" + HINT
    assert with_stage_hints("Промпт.", []) == "Промпт."
