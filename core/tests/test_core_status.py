"""Сводка ядра целиком на подделках: колонки в /status и проверка видов при правке настроек."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core_harness import (
    FAST_ARBITRATION,
    HEADERS,
    QUIET_WHISPER,
    TOOLS_OLLAMA,
    client,
    connect,
    eventually,
    fake_kinds,
    make_core,
    ollama_factory,
)

from fakes.fake_executor import FakeOllama
from smartesp.config import ExecutorConfig
from smartesp.contracts import Executor, ExecutorError
from smartesp.wiring import finish, start, stop

NAMED = FAST_ARBITRATION + 'devices:\n  "AA:BB": {name: Спальня}\n'


async def test_status_lists_connected_and_never_seen_speakers(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])), NAMED)
    start(core)
    await eventually(lambda: core.core.state == "ready")
    await connect(core, "kitchen")
    async with client(core) as http:
        response = await http.get("/api/v1/status", headers=HEADERS)
    assert response.status_code == 200
    devices = {d["device_id"]: d for d in response.json()["devices"]}
    assert devices["kitchen"]["connected"] and devices["kitchen"]["remote"] == "10.0.0.7:5000"
    assert devices["AA:BB"]["name"] == "Спальня"
    assert not devices["AA:BB"]["connected"] and devices["AA:BB"]["remote"] == ""
    await stop(core)
    await finish(core)


async def test_patch_with_unknown_kind_is_rejected_and_not_saved(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    async with client(core) as http:
        for patch in ({"stt": {"kind": "whisperx"}}, {"stages": [{"kind": "mood"}]}):
            response = await http.patch("/api/v1/config", json=patch, headers=HEADERS)
            assert response.status_code == 422
            assert response.json()["status"] == "invalid"
            assert "kind=" in response.json()["error"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    await core.core.aclose()
    await finish(core)


async def test_executors_and_stages_together_build_one_network(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    core = make_core(tmp_path, fake_kinds(ollama_factory(made)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    applied = core.bus.subscribe()
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"stages": [], "executors": [{**entry, "model": "other"}]})
    async with asyncio.timeout(2):
        change = await anext(e.data async for e in applied if e.kind == "change_applied")
    assert change["ok"], change
    # старт — сеть из двух, правка — одна сеть из одного (одна сборка, не две)
    assert [e.model for e in made] == [entry["model"], "deepseek-r1:8b", "other"]
    assert made[2].warmed == 1 and made[0].unloaded == [1.0] and made[1].unloaded == [1.0]
    await applied.aclose()
    await stop(core)
    await finish(core)


async def test_config_shows_dispatcher_prompt_with_stage_rules(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])), QUIET_WHISPER)
    entry = core.config.entry_executor()
    async with client(core) as http:
        prompt = (await http.get("/api/v1/config", headers=HEADERS)).json()["dispatcher_prompt"]
        assert prompt.startswith(entry.system_prompt) and "[style:quiet]" in prompt
        applied = core.bus.subscribe()
        await core.core.patch_config({"stages": []})
        async with asyncio.timeout(2):
            change = await anext(e.data async for e in applied if e.kind == "change_applied")
        assert change["ok"], change
        prompt = (await http.get("/api/v1/config", headers=HEADERS)).json()["dispatcher_prompt"]
        assert prompt == entry.system_prompt
    await applied.aclose()
    await core.core.aclose()
    await finish(core)


async def test_config_shows_prompts_of_all_executors_with_rule(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])), QUIET_WHISPER, ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: core.core.state == "ready")  # сборка сети узнала возможности моделей
    async with client(core) as http:
        config = (await http.get("/api/v1/config", headers=HEADERS)).json()
    prompts = config["executor_prompts"]
    assert set(prompts) == {"dispatcher", "big"}
    assert config["dispatcher_prompt"] == prompts["dispatcher"] and "delegate" in prompts["dispatcher"]
    assert "[style:quiet]" in prompts["big"] and "delegate" not in prompts["big"]
    await stop(core)
    await finish(core)


async def test_status_shows_member_that_did_not_warm_up(tmp_path: Path) -> None:
    def factory(config: ExecutorConfig) -> Executor:
        if config.id == "big":
            return FakeOllama(["Да."], config.model, warm_error=ExecutorError("нет модели deepseek"))
        return FakeOllama(["Да."], config.model)

    core = make_core(tmp_path, fake_kinds(factory))
    start(core)
    await eventually(lambda: core.core.state == "ready" and bool(core.live.members_warmth))
    async with client(core) as http:
        status = (await http.get("/api/v1/status", headers=HEADERS)).json()
    (big,) = status["executors"]
    assert big["id"] == "big" and not big["ready"] and "deepseek" in big["error"]
    await stop(core)
    await finish(core)
