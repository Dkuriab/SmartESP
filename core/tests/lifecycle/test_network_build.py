"""Сеть исполнителей из настроек: цели, промпты, проверка умения инструментов."""

from __future__ import annotations

import pytest

from fakes.fake_executor import FakeOllama
from smartesp.config import Config, ExecutorConfig, StageConfig
from smartesp.config.models import BIG_WHEN, DelegateLink
from smartesp.contracts import Executor
from smartesp.lifecycle import (
    CapabilityCache,
    Kinds,
    NetworkPrompts,
    StartupError,
    build_network,
    executor_prompts,
    with_stage_hints,
)
from smartesp.main import STAGE_KINDS
from smartesp.network import Target, delegate_rule


class Made:
    """Фабрика исполнителей: запоминает каждый собранный FakeOllama."""

    def __init__(self) -> None:
        self.executors: list[FakeOllama] = []

    def __call__(self, config: ExecutorConfig) -> Executor:
        executor = FakeOllama([], config.model, prompt=config.system_prompt)
        self.executors.append(executor)
        return executor

    def prompt(self, model: str) -> str:
        return next(e.prompt for e in self.executors if e.model == model)


def kinds(made: Made) -> Kinds:
    return Kinds(stt={}, tts={}, executors={"ollama": made}, stages=STAGE_KINDS)


class Capabilities:
    """Поддельный model_capabilities: по модели — набор возможностей, плюс счёт вызовов."""

    def __init__(self, by_model: dict[str, frozenset[str]] | None = None) -> None:
        self.by_model = by_model or {}
        self.calls: list[str] = []

    async def __call__(self, model: str) -> frozenset[str]:
        self.calls.append(model)
        return self.by_model.get(model, frozenset({"completion", "tools"}))


def two_executors(when: str = "", description: str = "", big_model: str = "big") -> Config:
    entry = ExecutorConfig(
        id="dispatcher",
        name="Диспетчер",
        model="small",
        entry=True,
        system_prompt="Промпт диспетчера.",
        delegates=[DelegateLink(to="big", when=when)],
    )
    big = ExecutorConfig(
        id="big", name="Большая модель", model=big_model, system_prompt="Промпт big.", description=description
    )
    return Config(executors=[entry, big])


async def test_default_network_offers_big_to_entry_with_rule_in_prompt() -> None:
    made = Made()
    config = Config()
    _, network = await build_network(config, kinds(made), Capabilities())
    assert network.id == "dispatcher" and list(network.members) == ["dispatcher", "big"]
    target = Target("big", "Большая модель", BIG_WHEN)
    entry = network.members["dispatcher"]
    assert entry.targets == (target,) and entry.tools_ok and entry.name == "Диспетчер"
    prompt = made.prompt(config.entry_executor().model)
    assert prompt.startswith(config.entry_executor().system_prompt)
    assert prompt.endswith(delegate_rule([target]))
    assert network.members["big"].targets == ()
    assert "delegate" not in made.prompt("deepseek-r1:8b")


async def test_model_without_tools_gets_no_rule() -> None:
    made = Made()
    capabilities = Capabilities({"small": frozenset({"completion"})})
    _, network = await build_network(two_executors(when="сложное"), kinds(made), capabilities)
    entry = network.members["dispatcher"]
    assert not entry.tools_ok and network.members["big"].tools_ok
    assert "delegate" not in made.prompt("small")


async def test_link_without_when_and_description_is_dropped() -> None:
    _, network = await build_network(two_executors(), kinds(Made()), Capabilities())
    assert network.members["dispatcher"].targets == ()


async def test_empty_when_takes_target_description() -> None:
    made = Made()
    config = two_executors(description="рассуждения")
    _, network = await build_network(config, kinds(made), Capabilities())
    assert network.members["dispatcher"].targets == (Target("big", "Большая модель", "рассуждения"),)
    assert "— Большая модель: рассуждения." in made.prompt("small")


async def test_target_prompt_includes_stage_hints() -> None:
    made = Made()
    await build_network(two_executors(when="сложное"), kinds(made), Capabilities())
    assert made.prompt("big").startswith("Промпт big.") and "[style:quiet]" in made.prompt("big")
    assert "[style:quiet]" in made.prompt("small")


async def test_no_stages_keeps_own_prompts() -> None:
    made = Made()
    config = two_executors().model_copy(update={"stages": []})
    await build_network(config, kinds(made), Capabilities())
    assert made.prompt("small") == "Промпт диспетчера." and made.prompt("big") == "Промпт big."


async def test_capabilities_asked_once_per_model() -> None:
    capabilities = Capabilities()
    await build_network(two_executors(big_model="small"), kinds(Made()), capabilities)
    assert capabilities.calls == ["small"]


async def test_unknown_executor_kind_is_startup_error() -> None:
    config = Config(executors=[ExecutorConfig(id="a", name="А", kind="nope", model="m", entry=True)])
    with pytest.raises(StartupError, match="nope"):
        await build_network(config, kinds(Made()), Capabilities())


async def test_executor_prompts_match_built_prompts() -> None:
    made = Made()
    config = two_executors(when="сложное")
    await build_network(config, kinds(made), Capabilities({"big": frozenset()}))
    prompts = executor_prompts(config, kinds(Made()), {"dispatcher": True, "big": False})
    assert prompts == {"dispatcher": made.prompt("small"), "big": made.prompt("big")}


def test_executor_prompts_without_tools_have_no_rule() -> None:
    prompts = executor_prompts(two_executors(when="сложное"), kinds(Made()), {})
    assert all("delegate" not in prompt for prompt in prompts.values())


async def test_network_prompts_use_known_capabilities() -> None:
    config = two_executors(when="сложное")
    cache = CapabilityCache(Capabilities({"big": frozenset()}))
    prompts = NetworkPrompts(lambda: config, kinds(Made()), cache)
    assert "delegate" not in prompts.entry()  # возможности ещё не известны
    await cache.get("small")
    assert prompts.entry() == prompts.all()["dispatcher"] and "delegate" in prompts.entry()


async def test_capability_cache_keeps_known_and_retries_empty() -> None:
    capabilities = Capabilities({"gone": frozenset()})
    cache = CapabilityCache(capabilities)
    assert await cache.supports_tools("small") and await cache.supports_tools("small")
    assert not await cache.supports_tools("gone") and not await cache.supports_tools("gone")
    assert capabilities.calls == ["small", "gone", "gone"]  # пустое не запоминается: модель могут скачать
    assert cache.known("small") == frozenset({"completion", "tools"}) and cache.known("gone") == frozenset()


async def test_capability_cache_swallows_errors() -> None:
    async def broken(model: str) -> frozenset[str]:
        raise RuntimeError("ollama упала")

    assert await CapabilityCache(broken).get("small") == frozenset()


def test_stage_hint_is_appended() -> None:
    stage = STAGE_KINDS["whisper_detect"](StageConfig(kind="whisper_detect"))
    assert with_stage_hints("Промпт.", [stage]).startswith("Промпт.\n")
