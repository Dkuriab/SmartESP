"""Пульт с настоящими ConfigFile и VoiceManager: они подходят под договоры пульта."""

import asyncio
from pathlib import Path

from fakes.fake_control import FakeVoices
from fakes.fake_events import RecordingSink
from smartesp.config import ConfigFile, load_config
from smartesp.contracts import ConfigStore, TextToSpeech, VoicePort
from smartesp.control import Core
from smartesp.events import EventBus
from smartesp.tts import VoiceManager


async def _nothing() -> list[str]:
    return []


async def _no_models() -> list[tuple[str, int]]:
    return []


async def test_config_file_round_trip_through_core(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    store = ConfigFile(path)
    store.load()
    port: ConfigStore = store
    events = RecordingSink()
    core = Core(
        port,
        {},
        events=events,
        feed=EventBus(),
        voices=FakeVoices(),
        models=_no_models,
        loaded=_nothing,
        devices=list,
        version="0",
    )
    assert (await core.patch_config({"version": 4})).status == "invalid"
    first = await core.patch_config({"server": {"port": 9001}})
    second = await core.patch_config({"history": {"max_turns": 3}})
    assert first.status == "restart_required"
    assert second.status == "accepted"
    async with asyncio.timeout(1):
        while len(events.events) < 2:
            await asyncio.sleep(0)
    assert [data["ok"] for _, data in events.events] == [True, True]
    saved = load_config(path)
    assert saved.server.port == 9001
    assert sorted(core.config()["overridden"]) == ["history.max_turns", "server.port"]
    await core.aclose()


async def test_voice_manager_satisfies_voice_port(tmp_path: Path) -> None:
    def on_ready(tts: TextToSpeech, kind: str, voice: str) -> None:
        pass

    manager = VoiceManager(tmp_path, {}, on_ready)
    port: VoicePort = manager
    assert port.state()["state"] == "missing"
    await manager.aclose()
