"""Тесты очереди изменений пульта: порядок применения, сбои, перезапуск, голос."""

import asyncio

from control_harness import Harness

from smartesp.contracts import ChangeResult


async def test_change_is_accepted_then_built_swapped_released_saved_announced() -> None:
    h = Harness()
    first = await h.core.patch_config({"history": {"turns": 20}})
    assert first == ChangeResult(1, "accepted")
    await h.settle(1)
    assert h.log == [
        "build history",
        "swap history",
        "release history:initial",  # старая часть — после подмены
        "save",
        "event change_applied",
    ]
    assert h.sections["history"].current == "history:{'turns': 20}"
    assert h.store.current["history"] == {"turns": 20}
    assert h.applied() == [{"change_id": 1, "ok": True, "error": None, "sections": ["history"]}]
    second = await h.core.patch_config({"history": {"turns": 30}})
    assert second.change_id == 2
    await h.core.aclose()


async def test_build_failure_leaves_old_parts_and_file() -> None:
    h = Harness()
    h.sections["executors"].error = RuntimeError("модель не влезла")
    result = await h.core.patch_config(
        {"devices": {"a": "Кухня"}, "executors": [{"id": "main", "model": "big"}]}
    )
    assert result.status == "accepted"
    await h.settle(1)
    # собранная, но не подменённая часть освобождается; подмен и записи нет
    assert h.log == [
        "build devices",
        "build executors",
        "release devices:{'a': 'Кухня'}",
        "event change_applied",
    ]
    assert h.sections["devices"].current == "devices:initial"
    assert h.store.saved == []
    assert h.applied() == [
        {"change_id": 1, "ok": False, "error": "модель не влезла", "sections": ["devices", "executors"]}
    ]
    await h.core.aclose()


async def test_second_change_waits_for_first_and_keeps_both() -> None:
    h = Harness()
    h.sections["history"].gate = asyncio.Event()
    first = await h.core.patch_config({"history": {"turns": 20}})
    second = await h.core.patch_config({"devices": {"a": "Кухня"}})
    assert (first.change_id, second.change_id) == (1, 2)
    await h.spin()
    assert h.log == ["build history"]  # второе ждёт, пока идёт первое
    assert (await h.core.status())["applying"] is True
    h.sections["history"].gate.set()
    await h.settle(2)
    assert h.log == [
        "build history",
        "swap history",
        "release history:initial",
        "save",
        "event change_applied",
        "build devices",
        "swap devices",
        "release devices:initial",
        "save",
        "event change_applied",
    ]
    # второе слито поверх первого: в файле оба изменения
    assert h.store.saved[-1]["history"] == {"turns": 20}
    assert h.store.saved[-1]["devices"] == {"a": "Кухня"}
    assert [e["change_id"] for e in h.applied()] == [1, 2]
    assert (await h.core.status())["applying"] is False
    await h.core.aclose()


async def test_restart_section_is_saved_without_building() -> None:
    h = Harness()
    assert (await h.core.status())["restart_required"] is False
    result = await h.core.patch_config({"server": {"port": 9000}})
    assert result == ChangeResult(1, "restart_required")
    await h.settle(1)
    assert h.log == ["save", "event change_applied"]
    assert h.store.current["server"] == {"port": 9000}
    assert h.applied() == [{"change_id": 1, "ok": True, "error": None, "sections": ["server"]}]
    assert (await h.core.status())["restart_required"] is True
    await h.core.aclose()


async def test_mixed_change_applies_live_part_and_needs_restart() -> None:
    h = Harness()
    result = await h.core.patch_config({"stt": {"kind": "other"}, "history": {"turns": 5}})
    assert result.status == "restart_required"
    await h.settle(1)
    assert h.log[:2] == ["build history", "swap history"]
    assert h.store.current["stt"] == {"kind": "other"}
    assert h.applied()[0]["sections"] == ["stt", "history"]
    assert (await h.core.status())["restart_required"] is True
    await h.core.aclose()


async def test_invalid_patch_is_rejected_at_once() -> None:
    h = Harness()
    result = await h.core.patch_config({"nope": 1})
    assert result == ChangeResult(1, "invalid", "неизвестный раздел nope")
    await h.spin()
    assert h.log == []
    assert h.store.saved == []
    assert (await h.core.patch_config({"history": {"turns": 3}})).change_id == 2
    await h.core.aclose()


async def test_unchanged_sections_are_not_rebuilt() -> None:
    h = Harness()
    await h.core.patch_config({"history": {"turns": 10}, "devices": {"a": "Кухня"}})
    await h.core.patch_config({"history": {"turns": 10}})
    await h.settle(2)
    assert [line for line in h.log if line.startswith("build")] == ["build devices"]
    assert h.applied()[1] == {"change_id": 2, "ok": True, "error": None, "sections": []}
    await h.core.aclose()


async def test_voice_change_opens_voice_then_saves() -> None:
    h = Harness()
    result = await h.core.patch_config({"tts": {"kind": "vosk", "voice": "female_1"}})
    assert result.status == "accepted"
    await h.settle(1)
    assert h.voices.opened == [("vosk", "female_1", False)]
    assert h.log == ["open vosk/female_1", "save", "event change_applied"]
    assert h.applied() == [{"change_id": 1, "ok": True, "error": None, "sections": ["tts"]}]
    await h.core.aclose()


async def test_failed_voice_keeps_file_and_releases_built_parts() -> None:
    h = Harness()
    h.voices.open_result = False
    h.voices.voice_state = {"kind": "vosk", "voice": "female_1", "state": "failed", "error": "нет сети"}
    await h.core.patch_config({"tts": {"voice": "female_1", "kind": "vosk"}, "history": {"turns": 1}})
    await h.settle(1)
    assert h.log == [
        "build history",
        "open vosk/female_1",
        "release history:{'turns': 1}",
        "event change_applied",
    ]
    assert h.sections["history"].current == "history:initial"
    assert h.store.saved == []
    assert h.applied() == [{"change_id": 1, "ok": False, "error": "нет сети", "sections": ["tts", "history"]}]
    await h.core.aclose()


async def test_unchanged_voice_is_not_reopened() -> None:
    h = Harness()
    await h.core.patch_config({"tts": {"kind": "silero"}, "history": {"turns": 2}})
    await h.settle(1)
    assert h.voices.opened == []
    await h.core.aclose()


async def test_aclose_cancels_running_change_and_refuses_new() -> None:
    h = Harness()
    h.sections["history"].gate = asyncio.Event()
    await h.core.patch_config({"history": {"turns": 20}})
    await h.spin()
    await h.core.patch_config({"devices": {"a": "Кухня"}})  # ждёт в очереди
    await h.core.aclose()
    assert h.store.saved == []
    assert h.applied() == []
    assert (await h.core.status())["applying"] is False
    late = await h.core.patch_config({"history": {"turns": 30}})
    assert late.status == "invalid"
    assert late.error == "ядро останавливается"
