"""Связка kinds.py: настройки → описания участников, обработчики и сеть исполнителей."""

from __future__ import annotations

import pytest

from fakes.fake_executor import FakeOllama
from fakes.no_connectors import NO_DEFAULT_CONNECTORS
from smartesp.config import Config, ExecutorConfig, StageConfig
from smartesp.config.connectors import REPO_DIR
from smartesp.config.models import BIG_WHEN, DelegateLink
from smartesp.contracts import Executor, ToolResult, ToolSpec
from smartesp.kinds import (
    Kinds,
    StartupError,
    build_answering,
    connector_specs,
    member_specs,
    prompt_stages,
)
from smartesp.main import STAGE_KINDS
from smartesp.network import MemberSpec, Target, delegate_rule
from smartesp.tools import ConnectorSpec


async def with_tools(model: str) -> frozenset[str]:
    return frozenset({"completion", "tools"})


def kinds(made: list[FakeOllama]) -> Kinds:
    def make(config: ExecutorConfig, _: Config) -> Executor:
        made.append(FakeOllama([], config.model, prompt=config.system_prompt))
        return made[-1]

    return Kinds(stt={}, tts={}, executors={"ollama": make}, stages=STAGE_KINDS)


async def test_default_settings_build_network_with_big_and_rule() -> None:
    made: list[FakeOllama] = []
    config = Config(stages=[StageConfig(kind="whisper_detect", quiet_reply=True), StageConfig(kind="clock")])
    analyze, network = await build_answering(config, kinds(made), with_tools)
    target = Target("big", "Большая модель", BIG_WHEN)
    assert list(network.members) == ["dispatcher", "big"] and network.members["dispatcher"].targets == (
        target,
    )
    entry_prompt = made[0].prompt
    assert made[0].model == config.entry_executor().model
    assert entry_prompt.startswith(config.entry_executor().system_prompt) and "[style:quiet]" in entry_prompt
    assert entry_prompt.endswith(delegate_rule([target]))
    plain, big = made[1], made[2]  # вариант диспетчера без правила передачи, затем big
    assert plain.model == made[0].model and "delegate" not in plain.prompt
    assert big.model == "deepseek-r1:8b" and "[style:quiet]" in big.prompt
    assert callable(analyze)


async def test_unknown_executor_kind_is_startup_error() -> None:
    config = Config(executors=[ExecutorConfig(id="a", name="А", kind="nope", model="m", entry=True)])
    with pytest.raises(StartupError, match="nope"):
        await build_answering(config, kinds([]), with_tools)


def test_member_specs_and_prompt_stages_follow_settings() -> None:
    entry = ExecutorConfig(
        id="a",
        name="А",
        model="m",
        entry=True,
        system_prompt="П.",
        delegates=[DelegateLink(to="b", when="x")],
    )
    big = ExecutorConfig(id="b", name="Б", model="n", description="описание")
    config = Config(executors=[entry, big])
    assert member_specs(config) == [
        MemberSpec("a", "А", "", "m", "П.", (("b", "x"),)),
        MemberSpec("b", "Б", "описание", "n", "", ()),
    ]
    assert [s.name for s in prompt_stages(config, kinds([]))] == ["whisper_detect", "clock", "system"]


class Box:
    """Поддельный ToolBox с одним инструментом."""

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec("note_add", "Записать", {"type": "object"})]

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        return ToolResult("ок")


async def test_toolbox_tools_go_to_members_with_tools() -> None:
    _, network = await build_answering(Config(), kinds([]), with_tools, Box())
    assert [t.name for t in network.members["dispatcher"].tools] == ["note_add"]


def test_connector_specs_expand_repo_placeholder() -> None:
    notes = connector_specs(Config())[0]
    assert notes.args[2] == str(REPO_DIR / "connectors" / "notes")


def test_connector_specs_follow_settings() -> None:
    config = Config.model_validate(
        {
            "connectors": [
                *NO_DEFAULT_CONNECTORS,
                {"id": "a", "name": "А", "command": "x", "args": ["1", "2"], "env": {"K": "v"}},
                {"id": "b", "name": "Б", "command": "y", "enabled": False},
            ]
        }
    )
    assert connector_specs(config) == [
        ConnectorSpec("a", "А", "x", ("1", "2"), {"K": "v"}, True),
        ConnectorSpec("b", "Б", "y", (), {}, False),
    ]


async def test_default_settings_have_no_whisper_style_rule() -> None:
    made: list[FakeOllama] = []
    await build_answering(Config(), kinds(made), with_tools)
    assert all("[style:quiet]" not in m.prompt for m in made)


def test_cloud_executor_gets_service_settings_and_cloud_model_key() -> None:
    from smartesp.executors import CloudExecutor
    from smartesp.main import EXECUTOR_KINDS

    big = ExecutorConfig(id="big", name="Б", kind="cloud", model="google/gemini-2.5-flash")
    config = Config(executors=[*Config().executors[:1], big]).model_copy(
        update={"cloud": Config().cloud.model_copy(update={"api_key": "k"})}
    )
    assert [s.model for s in member_specs(config)] == ["gpt-oss:20b", "@cloud/google/gemini-2.5-flash"]
    executor = EXECUTOR_KINDS["cloud"](big, config)
    assert isinstance(executor, CloudExecutor) and executor.models() == frozenset(
        {"@cloud/google/gemini-2.5-flash"}
    )
    assert (
        vars(executor)["_key"] == "k"
        and vars(executor)["_url"] == "https://openrouter.ai/api/v1/chat/completions"
    )
