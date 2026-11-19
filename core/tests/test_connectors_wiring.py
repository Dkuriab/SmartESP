"""Коннекторы в живом ядре: фоновый старт, инструменты в сети, правка на лету, объявления, остановка.

Коннектор — маленький тестовый MCP-сервер из tests/tools (запуск через sys.executable).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from core_harness import (
    HEADERS,
    TOOLS_OLLAMA,
    ask,
    client,
    connect,
    eventually,
    fake_kinds,
    make_core,
    sent_types,
)

from fakes.fake_executor import FakeOllama
from smartesp.config import ExecutorConfig
from smartesp.contracts import ChatMessage, Executor, ReplyPart, Subscription, ToolCall, ToolSpec
from smartesp.lifecycle import TOOLS_DEBOUNCE_S
from smartesp.network import ExecutorNetwork
from smartesp.wiring import Assembly, finish, start, stop

SERVER = str(Path(__file__).parent / "tools" / "mcp_test_server.py")
WAIT_S = TOOLS_DEBOUNCE_S + 8.0  # запуск коннектора + пауза перед пересборкой сети


def connector(cid: str, mode: str = "", enabled: bool = True) -> dict[str, object]:
    args = [SERVER, mode] if mode else [SERVER]
    return {"id": cid, "name": cid.upper(), "command": sys.executable, "args": args, "enabled": enabled}


def config_yaml(*connectors: dict[str, object]) -> str:
    # JSON — это YAML: так пути с любыми символами не ломают файл
    body = {"arbitration": {"window_ms": 20, "late_ms": 200}, "connectors": list(connectors)}
    return json.dumps(body, ensure_ascii=False)


def entry_tools(core: Assembly) -> list[str]:
    network = core.live.executor
    if not isinstance(network, ExecutorNetwork):
        return []  # стартовая сеть ещё не поставлена
    return [t.name for t in network.members["dispatcher"].tools]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ToolUser(FakeOllama):
    """Модель: сначала короткая фраза и вызов echo, после результата — ответ с ним."""

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(messages)
        self.tools.append(tuple(tools))
        if messages[-1].role == "tool":
            yield ReplyPart(f"Коннектор ответил: {messages[-1].content}.")
            return
        yield ReplyPart("Секунду.")
        yield ReplyPart(tool_call=ToolCall("echo", {"text": "эхо"}))


async def test_connectors_start_in_background_and_reach_the_network(tmp_path: Path) -> None:
    made: list[FakeOllama] = []

    def factory(config: ExecutorConfig) -> Executor:
        made.append(ToolUser([], config.model, prompt=config.system_prompt))
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory), config_yaml(connector("t")), ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: core.core.state == "ready", timeout=5)
    await eventually(lambda: "echo" in entry_tools(core), timeout=WAIT_S)
    async with client(core) as http:
        listed = (await http.get("/api/v1/connectors", headers=HEADERS)).json()
        status = (await http.get("/api/v1/status", headers=HEADERS)).json()
    assert [(c["id"], c["state"]) for c in listed] == [("t", "ready")]
    assert "echo" in listed[0]["tools"] and listed[0]["error"] == ""
    assert status["connectors"] == listed

    speaking, _ = await connect(core, "kitchen")
    ask(speaking, 1)
    await eventually(lambda: "reply_end" in sent_types(speaking), timeout=5)
    await eventually(lambda: bool(core.core.turns(1)))
    assert str(core.core.turns(1)[0]["answer"]).endswith("Коннектор ответил: эхо.")
    await stop(core)
    await finish(core)


async def test_editing_connectors_applies_live_and_rebuilds_network(tmp_path: Path) -> None:
    kinds = fake_kinds(lambda c: FakeOllama(["Да."], c.model))
    core = make_core(tmp_path, kinds, config_yaml(connector("t")), ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: "echo" in entry_tools(core), timeout=WAIT_S)
    pid = int((tmp_path / "connectors" / "t" / "pid").read_text())
    applied = core.bus.subscribe()

    result = await core.core.patch_config({"connectors": [connector("t", enabled=False)]})
    assert result.status == "accepted"
    assert (await next_change(applied))["ok"]
    await eventually(lambda: entry_tools(core) == [], timeout=WAIT_S)
    assert [(s.id, s.state) for s in core.tools.states()] == [("t", "disabled")]
    assert not alive(pid)
    assert core.core.config()["effective"]["connectors"][0]["enabled"] is False

    await core.core.patch_config({"connectors": [connector("t"), connector("u")]})
    assert (await next_change(applied))["ok"]
    await eventually(lambda: {"echo", "u_echo"} <= set(entry_tools(core)), timeout=WAIT_S)
    await applied.aclose()
    await stop(core)
    await finish(core)


async def next_change(events: Subscription) -> dict[str, object]:
    async for event in events:
        if event.kind == "change_applied":
            return event.data
    raise AssertionError("лента закрылась")


async def test_announcement_goes_to_announcer_from_connector(tmp_path: Path) -> None:
    kinds = fake_kinds(lambda c: FakeOllama(["Да."], c.model))
    core = make_core(tmp_path, kinds, config_yaml(connector("t")))
    said: list[tuple[str, str, str]] = []
    core.announcer.say = lambda device, text, source: said.append((device, text, source))  # type: ignore[method-assign]
    start(core)
    await eventually(lambda: core.tools.specs() != [], timeout=WAIT_S)
    result = await core.tools.call("announce", {"text": "Таймер «чай»: время вышло.", "person": None}, None)
    assert not result.is_error
    await eventually(lambda: bool(said))
    assert said == [("", "Таймер «чай»: время вышло.", "t")]  # "" — последняя активная колонка
    await stop(core)
    await finish(core)


async def test_stop_leaves_no_connector_processes(tmp_path: Path) -> None:
    yaml = config_yaml(connector("a"), connector("hang", "hang"))
    core = make_core(tmp_path, fake_kinds(lambda c: FakeOllama(["Да."], c.model)), yaml)
    start(core)
    await eventually(lambda: (tmp_path / "connectors" / "a" / "pid").exists(), timeout=WAIT_S)
    await eventually(lambda: (tmp_path / "connectors" / "hang" / "pid").exists(), timeout=WAIT_S)
    await eventually(lambda: core.core.state == "ready", timeout=5)
    pids = [int((tmp_path / "connectors" / cid / "pid").read_text()) for cid in ("a", "hang")]
    await stop(core)
    await finish(core)
    assert not any(alive(pid) for pid in pids)
    assert core.tools.states() == []
