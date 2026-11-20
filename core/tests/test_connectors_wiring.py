"""Коннекторы в живом ядре: фоновый старт, инструменты в сети, правка на лету, объявления, остановка.

Коннектор — маленький тестовый MCP-сервер из tests/tools (запуск через sys.executable).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
from fakes.no_connectors import NO_DEFAULT_CONNECTORS
from smartesp.config import ExecutorConfig
from smartesp.contracts import ChatMessage, Executor, ReplyPart, Subscription, ToolCall, ToolSpec
from smartesp.lifecycle import STOP_LIMIT_S, TOOLS_DEBOUNCE_S
from smartesp.network import ExecutorNetwork
from smartesp.wiring import Assembly, finish, start, stop

SERVER = str(Path(__file__).parent / "tools" / "mcp_test_server.py")
WAIT_S = TOOLS_DEBOUNCE_S + 8.0  # запуск коннектора + пауза перед пересборкой сети


def connector(cid: str, mode: str = "", enabled: bool = True) -> dict[str, object]:
    args = [SERVER, mode] if mode else [SERVER]
    return {"id": cid, "name": cid.upper(), "command": sys.executable, "args": args, "enabled": enabled}


def config_yaml(*connectors: dict[str, object]) -> str:
    # JSON — это YAML: так пути с любыми символами не ломают файл
    body = {
        "arbitration": {"window_ms": 20, "late_ms": 200},
        "connectors": [*NO_DEFAULT_CONNECTORS, *connectors],
    }
    return json.dumps(body, ensure_ascii=False)


def entry_tools(core: Assembly) -> list[str]:
    network = core.live.executor
    if not isinstance(network, ExecutorNetwork):
        return []  # стартовая сеть ещё не поставлена
    return [t.name for t in network.members["dispatcher"].tools]


def entry_executor(core: Assembly) -> object:
    network = core.live.executor
    return network.members["dispatcher"].executor if isinstance(network, ExecutorNetwork) else None


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
    used = {"executor": "dispatcher", "connector": "t", "tool": "echo", "ok": True}
    assert core.core.turns(1)[0]["tools"] == [used]  # живая подсветка знает коннектор вызова
    await stop(core)
    await finish(core)


async def test_editing_connectors_applies_live_and_rebuilds_network(tmp_path: Path) -> None:
    made: list[FakeOllama] = []

    def factory(config: ExecutorConfig) -> Executor:
        made.append(FakeOllama(["Да."], config.model))
        return made[-1]

    yaml_text = config_yaml(connector("t"), connector("u", enabled=False))
    core = make_core(tmp_path, fake_kinds(factory), yaml_text, ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: "echo" in entry_tools(core), timeout=WAIT_S)
    pid = int((tmp_path / "connectors" / "t" / "pid").read_text())
    applied = core.bus.subscribe()
    built = len(made)

    result = await core.core.patch_config({"connectors": [{"id": "t", "enabled": False}]})
    assert result.status == "accepted"
    assert (await next_change(applied))["ok"]
    await eventually(lambda: entry_tools(core) == [], timeout=WAIT_S)
    assert len(made) > built and all(e.warmed == 0 for e in made[built:])  # пересборка не грузит модели
    assert [(s.id, s.state) for s in core.tools.states()] == [("t", "disabled"), ("u", "disabled")]
    assert not alive(pid)
    assert core.core.config()["effective"]["connectors"][0]["enabled"] is False

    await core.core.patch_config({"connectors": [{"id": "t", "enabled": True}, {"id": "u", "enabled": True}]})
    assert (await next_change(applied))["ok"]
    await eventually(lambda: {"echo", "u_echo"} <= set(entry_tools(core)), timeout=WAIT_S)
    await applied.aclose()
    await stop(core)
    await finish(core)


async def test_api_cannot_set_connector_command_or_add_one(tmp_path: Path) -> None:
    kinds = fake_kinds(lambda c: FakeOllama(["Да."], c.model))
    core = make_core(tmp_path, kinds, config_yaml(connector("t", enabled=False)))
    start(core)
    await eventually(lambda: core.core.state == "ready", timeout=5)
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    marker = tmp_path / "pwned"
    shell = {"command": "/bin/sh", "args": ["-c", f"touch {marker}"]}
    attempts = ([{"id": "t", **shell}], [{"id": "x", "name": "x", **shell}], [{"id": "t", "env": {}}])
    async with client(core) as http:
        for entries in attempts:
            response = await http.patch("/api/v1/config", json={"connectors": entries}, headers=HEADERS)
            assert response.status_code == 422
            assert "меняют только в config.yaml" in response.json()["error"]
    await asyncio.sleep(0.3)
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    assert [(s.id, s.state) for s in core.tools.states()] == [("t", "disabled")]
    assert not marker.exists()
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


async def test_timer_announcement_reaches_connected_speaker_without_turns(tmp_path: Path) -> None:
    # после старта ядра никто не говорил: объявление — на первую подключённую колонку v3
    kinds = fake_kinds(lambda c: FakeOllama(["Да."], c.model))
    core = make_core(tmp_path, kinds, config_yaml(connector("t")))
    start(core)
    await eventually(lambda: core.tools.specs() != [], timeout=WAIT_S)
    speaking, _ = await connect(core, "kitchen", protocol=3)
    events = core.bus.subscribe()
    await core.tools.call("announce", {"text": "Таймер «чай»: время вышло.", "person": None}, None)
    await eventually(lambda: "reply_end" in sent_types(speaking))
    turn = next(m["turn"] for m in speaking.sent_json() if m["type"] == "announce")
    speaking.feed_json("playback_done", turn=turn)
    async with asyncio.timeout(2):
        async for event in events:
            if event.kind == "turn_finished" and event.data["kind"] == "announcement":
                assert (event.data["device_id"], event.data["status"]) == ("kitchen", "ok")
                assert event.data["path"] == ["t"]
                break
    await events.aclose()
    await stop(core)
    await finish(core)


async def test_stop_with_stubborn_connector_and_running_turn_fits_budget(tmp_path: Path) -> None:
    # ход договаривается ~9 с; упрямый коннектор (не выходит ни по EOF, ни по SIGTERM)
    # закрывается одновременно и не дольше ~3 с: вся остановка — в пределах 12 с
    slow = ["Это долгий ответ. "] * 6
    kinds = fake_kinds(lambda c: FakeOllama(slow, c.model, delay=1.5))
    core = make_core(tmp_path, kinds, config_yaml(connector("s", "stubborn")))
    start(core)
    await eventually(lambda: core.core.state == "ready", timeout=5)
    await eventually(lambda: [s.state for s in core.tools.states()] == ["ready"], timeout=WAIT_S)
    pid = int((tmp_path / "connectors" / "s" / "pid").read_text())
    speaking, _ = await connect(core, "kitchen")
    ask(speaking, 1)
    await eventually(lambda: "reply_start" in sent_types(speaking), timeout=5)
    began = time.monotonic()
    await stop(core)
    assert time.monotonic() - began < STOP_LIMIT_S
    assert speaking.closed
    assert not alive(pid)
    await finish(core)


async def test_tools_change_during_executors_edit_keeps_the_edit(tmp_path: Path) -> None:
    # правка сменила модель и ждёт конца хода (release); тем временем сменились инструменты —
    # пересборка идёт после правки и не возвращает прежнюю модель
    made: list[FakeOllama] = []

    def factory(config: ExecutorConfig) -> Executor:
        made.append(FakeOllama(["Раз. "] * 6, config.model, delay=0.6))  # ход ~3,6 с
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory), config_yaml(), ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: core.core.state == "ready", timeout=5)
    speaking, _ = await connect(core, "kitchen")
    ask(speaking, 1)
    await eventually(lambda: "reply_start" in sent_types(speaking), timeout=5)
    applied = core.bus.subscribe()
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})
    before = len(made)
    await core.core.patch_config({"executors": [{**entry, "model": "other"}]})
    core.refresh.changed()
    assert (await next_change(applied))["ok"]
    # пересборка под инструменты встала в очередь, пока release правки ждал конца хода
    await eventually(lambda: bool(core.core.turns(1)), timeout=8)
    await eventually(lambda: len(made) >= before + 2, timeout=5)  # исполнитель правки и пересборки
    await eventually(lambda: entry_executor(core) is made[-1], timeout=5)  # пересборка встала
    assert made[-1].model == "other"
    await applied.aclose()
    await stop(core)
    await finish(core)
