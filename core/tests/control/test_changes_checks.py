"""Очередь изменений: общий раздел собирается один раз, проверка всей правки до записи."""

from __future__ import annotations

import asyncio
from typing import Any

from control_harness import INITIAL, FakeSection, Harness

from fakes.fake_control import FakeConfigStore, FakeVoices
from fakes.fake_events import RecordingSink
from smartesp.contracts import ChangeResult
from smartesp.control import Core
from smartesp.control.changes import ChangeQueue


async def applied(events: RecordingSink, count: int) -> list[dict[str, object]]:
    async with asyncio.timeout(1):
        while True:
            found = [data for kind, data in events.events if kind == "change_applied"]
            if len(found) >= count:
                return found
            await asyncio.sleep(0)


async def test_shared_section_is_built_swapped_and_released_once() -> None:
    log: list[str] = []
    shared = FakeSection("executors", log).section()  # исполнитель зависит и от stages
    events = RecordingSink()
    queue = ChangeQueue(
        FakeConfigStore(INITIAL),
        {"executors": shared, "stages": shared},
        voices=FakeVoices(),
        events=events,
    )
    patch = {"executors": [{"id": "main", "model": "big"}], "stages": {"a": 1}}
    assert queue.submit(1, patch).status == "accepted"
    [change] = await applied(events, 1)
    assert change["ok"] and change["sections"] == ["executors", "stages"]
    assert log == ["build executors", "swap executors", "release executors:initial"]
    await queue.aclose()


def reject_whisperx(config: Any) -> None:
    if config["stt"]["kind"] == "whisperx":
        raise ValueError("Неизвестный stt kind='whisperx'")


def core_with(validate: Any) -> tuple[Core, Harness]:
    h = Harness()
    core = Core(
        h.store,
        {},
        events=h.events,
        feed=h.bus,
        voices=h.voices,
        models=h._models,  # pyright: ignore[reportPrivateUsage]
        loaded=h._loaded,  # pyright: ignore[reportPrivateUsage]
        devices=lambda: [],
        version="1",
        validate=validate,
    )
    return core, h


async def test_validator_rejects_patch_before_saving() -> None:
    core, h = core_with(reject_whisperx)
    result = await core.patch_config({"stt": {"kind": "whisperx"}})
    assert result == ChangeResult(1, "invalid", "Неизвестный stt kind='whisperx'")
    assert (await core.patch_config({"stt": {"kind": "other"}})).status == "restart_required"
    await h.settle(1)
    assert h.store.saved[-1]["stt"] == {"kind": "other"}
    await core.aclose()
    assert all(saved["stt"]["kind"] != "whisperx" for saved in h.store.saved)


async def test_download_of_voice_outside_catalog_is_invalid() -> None:
    h = Harness()
    h.voices.voice_catalog = [{"kind": "vosk", "voice": "female_1"}]
    result = await h.core.download_voice("vosk", "female_9")
    assert result == ChangeResult(1, "invalid", "Неизвестный голос vosk/female_9")
    assert (await h.core.download_voice("vosk", "female_1")).status == "accepted"
    await h.spin()
    assert h.voices.downloaded == [("vosk", "female_1")]
    await h.core.aclose()
