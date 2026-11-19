"""Пересборка разделов по текущим настройкам — в той же очереди, что правки (не гоняется с ними)."""

import asyncio

import pytest
from control_harness import Harness


async def test_rebuild_builds_current_settings_swaps_and_releases_without_save() -> None:
    h = Harness()
    await h.core.rebuild(["executors", "stages"])
    assert h.log == [
        "build executors",
        "build stages",
        "swap executors",
        "swap stages",
        "release executors:initial",
        "release stages:initial",
    ]
    assert h.store.saved == [] and h.applied() == []
    await h.core.aclose()


async def test_rebuild_during_edit_release_waits_and_uses_edited_settings() -> None:
    # (a) правка подменила исполнителей, release ждёт конца хода: пересборка не может
    # поставить исполнителей прежних настроек — она идёт после записи правки
    h = Harness()
    h.sections["executors"].release_gate = asyncio.Event()
    await h.core.patch_config({"executors": [{"id": "main", "model": "big"}]})
    await h.spin()
    rebuilding = asyncio.create_task(h.core.rebuild(["executors"]))
    await h.spin()
    assert h.log == ["build executors", "swap executors", "release executors:initial"]
    h.sections["executors"].release_gate.set()
    await rebuilding
    assert h.log[3:6] == ["save", "event change_applied", "build executors"]
    assert h.sections["executors"].current == "executors:[{'id': 'main', 'model': 'big'}]"
    await h.core.aclose()


async def test_rebuild_requested_while_edit_builds_runs_after_its_swap() -> None:
    # (b) смена инструментов посреди долгой сборки правки: пересборка после подмены правки
    h = Harness()
    h.sections["executors"].gate = asyncio.Event()
    await h.core.patch_config({"executors": [{"id": "main", "model": "big"}]})
    await h.spin()
    rebuilding = asyncio.create_task(h.core.rebuild(["executors"]))
    await h.spin()
    h.sections["executors"].gate.set()
    await rebuilding
    swaps = [i for i, line in enumerate(h.log) if line == "swap executors"]
    assert len(swaps) == 2 and h.log.index("save") < swaps[1]
    await h.core.aclose()


async def test_failed_rebuild_raises_and_releases_built_parts() -> None:
    h = Harness()
    h.sections["stages"].error = RuntimeError("модель не прогрелась")
    with pytest.raises(RuntimeError, match="не прогрелась"):
        await h.core.rebuild(["executors", "stages"])
    assert h.sections["executors"].current == "executors:initial"
    assert "release executors:[{'id': 'main', 'model': 'qwen'}]" in h.log
    await h.core.aclose()


async def test_rebuild_after_close_is_refused_and_pending_is_cancelled() -> None:
    h = Harness()
    h.sections["history"].gate = asyncio.Event()
    await h.core.patch_config({"history": {"turns": 20}})
    await h.spin()
    pending = asyncio.create_task(h.core.rebuild(["executors"]))
    await h.spin()
    await h.core.aclose()
    with pytest.raises(asyncio.CancelledError):
        await pending
    with pytest.raises(RuntimeError, match="останавливается"):
        await h.core.rebuild(["executors"])
