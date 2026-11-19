"""Жизнь ядра на подделках: смена исполнителей и речи на лету, выгрузка моделей, сеть и её пересборка."""

from __future__ import annotations

import asyncio
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
    ollama_factory,
    sent_types,
)

from fakes.fake_connection import FakeConnection
from fakes.fake_executor import FakeOllama
from smartesp import wiring
from smartesp.config import ExecutorConfig
from smartesp.contracts import Executor, ReplyPart, Subscription, ToolCall
from smartesp.network import ExecutorNetwork
from smartesp.wiring import Assembly, finish, start, stop


async def next_change(events: Subscription) -> dict[str, object]:
    """Данные следующего события change_applied."""
    async with asyncio.timeout(2):
        async for event in events:
            if event.kind == "change_applied":
                return event.data
    raise AssertionError("лента закрылась")


async def test_prompt_change_keeps_model_and_model_change_unloads_old(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    core = make_core(tmp_path, fake_kinds(ollama_factory(made)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    applied = core.bus.subscribe()

    await core.core.patch_config({"stages": []})
    assert (await next_change(applied))["ok"]
    # старт: made[0] — диспетчер, made[1] — big; правка stages: made[2], made[3]
    assert "[style:quiet]" in made[0].prompt and "[style:quiet]" in made[1].prompt
    assert "[style:quiet]" not in made[2].prompt and "[style:quiet]" not in made[3].prompt
    assert made[0].unloaded == [] and made[1].unloaded == []  # те же модели: выгружать нельзя
    await eventually(lambda: made[3].warmed == 1)  # big греется в фоне

    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "other"}]})
    change = await next_change(applied)
    assert change["ok"], change
    assert made[-1].model == "other" and made[-1].warmed == 1
    assert made[2].unloaded == [1.0] and made[3].unloaded == [1.0]  # обе модели ушли из сети
    await applied.aclose()
    await stop(core)
    assert made[-1].unloaded == [1.0]
    await finish(core)


async def test_stop_mid_release_unloads_old_and_new_models(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    answer = ["Раз. ", "Два. ", "Три."]
    core = make_core(tmp_path, fake_kinds(ollama_factory(made, answer, delay=0.15)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    speaking, _ = await connect(core, "kitchen")
    startup = core.live.executor
    ask(speaking, 1)
    await eventually(lambda: "reply_start" in sent_types(speaking))
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "other"}]})
    await eventually(lambda: len(made) == 3 and core.live.executor is not startup)  # старая ждёт хода
    assert made[0].unloaded == [] and made[1].unloaded == []

    await stop(core)
    assert made[0].unloaded == [1.0]  # старые модели выгружены один раз, хоть release и отменён
    assert made[1].unloaded == [1.0]
    assert made[2].model == "other" and made[2].unloaded == [1.0]
    await finish(core)


async def test_stop_mid_build_unloads_model_being_warmed(tmp_path: Path) -> None:
    made: list[FakeOllama] = []

    def factory(config: ExecutorConfig) -> Executor:
        gate = asyncio.Event() if config.model == "big" else None
        made.append(FakeOllama(["Да."], config.model, warm_gate=gate))
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    entry = core.config.entry_executor().model_dump(exclude={"delegates"})  # без связи на big
    await core.core.patch_config({"executors": [{**entry, "model": "big"}]})
    await eventually(lambda: len(made) == 3)  # новая модель греется
    await stop(core)
    assert made[2].model == "big" and made[2].unloaded == [1.0]
    assert made[0].unloaded == [1.0] and made[1].unloaded == [1.0]
    await finish(core)


async def test_turn_with_handoff_goes_through_network(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    delegate = ToolCall("delegate", {"executor": "big", "task": "Объясни теорию относительности"})

    def factory(config: ExecutorConfig) -> Executor:
        parts = ["Сейчас спрошу большую модель. ", ReplyPart(tool_call=delegate)]
        if config.id == "big":
            parts = ["Это долгий рассказ про пространство и время."]
        made.append(FakeOllama(parts, config.model, prompt=config.system_prompt))
        return made[-1]

    core = make_core(tmp_path, fake_kinds(factory), ollama=TOOLS_OLLAMA)
    start(core)
    await eventually(lambda: core.core.state == "ready")
    assert "delegate" in made[0].prompt and "Большая модель" in made[0].prompt
    speaking, _ = await connect(core, "kitchen")
    ask(speaking, 1)
    await eventually(lambda: "reply_end" in sent_types(speaking))
    big = made[2]  # диспетчер, его вариант без правила передачи, затем big
    assert len(big.calls) == 1 and "Задача от диспетчера" in big.calls[0][-1].content
    async with client(core) as http:
        await eventually(lambda: bool(core.core.turns(1)))
        turns = (await http.get("/api/v1/turns", headers=HEADERS)).json()
    assert turns[0]["path"] == ["dispatcher", "big"]
    assert turns[0]["delegations"][0]["to"] == "big"
    await stop(core)
    await finish(core)


async def test_network_rebuilt_with_delegation_once_ollama_is_up(tmp_path: Path) -> None:
    up = [False]

    async def capabilities(model: str) -> frozenset[str]:
        if not up[0]:
            raise ConnectionError("Ollama не запущена")
        return frozenset({"completion", "tools"})

    made: list[FakeOllama] = []
    ollama = wiring.Ollama(TOOLS_OLLAMA.models, TOOLS_OLLAMA.loaded, capabilities)
    core = make_core(tmp_path, fake_kinds(ollama_factory(made)), ollama=ollama)
    start(core)
    await eventually(lambda: core.core.state == "ready")
    startup = core.live.executor
    assert isinstance(startup, ExecutorNetwork) and not startup.members["dispatcher"].tools_ok
    assert not await core.retry.check()  # Ollama всё ещё нет
    up[0] = True
    assert await core.retry.check()
    network = core.live.executor
    assert isinstance(network, ExecutorNetwork) and network is not startup
    assert network.members["dispatcher"].tools_ok and "delegate" in made[2].prompt
    await stop(core)
    assert core.retrying is not None and core.retrying.done()
    await finish(core)


async def next_finished(events: Subscription, kind: str) -> dict[str, object]:
    """Данные следующего события turn_finished вида kind ("turn" или "announcement")."""
    async with asyncio.timeout(2):
        async for event in events:
            if event.kind == "turn_finished" and event.data["kind"] == kind:
                return event.data
    raise AssertionError("лента закрылась")


async def announce_heard(core: Assembly, speaking: FakeConnection, events: Subscription, text: str) -> None:
    """Объявление ядра на колонке: колонка доигрывает его, ждём событие «прозвучало»."""
    ends = sent_types(speaking).count("reply_end")
    core.announcer.say("kitchen", text, "dispatcher")
    await eventually(lambda: sent_types(speaking).count("reply_end") > ends)
    speaking.feed_json("playback_done", turn=announce_turns(speaking)[-1])
    assert (await next_finished(events, "announcement"))["status"] == "ok"


def announce_turns(conn: FakeConnection) -> list[int]:
    return [m["turn"] for m in conn.sent_json() if m["type"] == "announce"]


async def test_speech_section_live(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([], ["Какой город?"])))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    speaking, _ = await connect(core, "kitchen", protocol=3)
    events = core.bus.subscribe()
    await core.core.patch_config({"speech": {"listen_after_question": False}})
    assert (await next_change(events))["ok"]

    await announce_heard(core, speaking, events, "Слышно?")
    ask(speaking, 1)  # ответ «Какой город?» — вопрос Кузи
    await next_finished(events, "turn")  # listen_after уже ждёт playback_done хода
    speaking.feed_json("playback_done", turn=1)
    await asyncio.sleep(0.1)
    assert "listen" not in sent_types(speaking)  # выключено и у объявлений, и у ходов

    await core.core.patch_config({"speech": {"listen_after_question": True}})
    assert (await next_change(events))["ok"]
    await announce_heard(core, speaking, events, "Слышно?")
    await eventually(lambda: "listen" in sent_types(speaking))
    await events.aclose()
    await stop(core)
    await finish(core)
