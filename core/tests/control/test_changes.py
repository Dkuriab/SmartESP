"""Тесты очереди изменений пульта: порядок применения, сбои, перезапуск, голос."""

import asyncio

from control_harness import Harness

from fakes.fake_control import FakeConfigStore, FakeVoices
from fakes.fake_events import RecordingSink
from smartesp.contracts import ChangeResult
from smartesp.control.changes import ChangeQueue


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
    await h.spin()
    assert [line for line in h.log if line != "open silero/xenia"] == [
        "build history",
        "open vosk/female_1",
        "release history:{'turns': 1}",
        "event change_applied",
    ]
    assert h.sections["history"].current == "history:initial"
    assert h.store.saved == []
    assert h.applied() == [{"change_id": 1, "ok": False, "error": "нет сети", "sections": ["tts", "history"]}]
    # менеджер голосов возвращают к записанному голосу, с повторами
    assert h.voices.opened == [("vosk", "female_1", False), ("silero", "xenia", True)]
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
    assert late.status == "stopping"
    assert late.error == "ядро останавливается"
    download = await h.core.download_voice("vosk", "female_1")
    assert download.status == "stopping"
    await h.spin()
    assert h.voices.downloaded == []


async def test_waiting_release_holds_next_change() -> None:
    h = Harness()
    h.sections["history"].release_gate = asyncio.Event()
    await h.core.patch_config({"history": {"turns": 20}})
    await h.core.patch_config({"devices": {"a": "Кухня"}})
    await h.spin()
    # release ждёт (например, конца звучащего хода) — следующая правка ждёт тоже
    assert h.log == ["build history", "swap history", "release history:initial"]
    assert (await h.core.status())["applying"] is True
    h.sections["history"].release_gate.set()
    await h.settle(2)
    assert h.log[3:6] == ["save", "event change_applied", "build devices"]
    await h.core.aclose()


async def test_good_failed_good_changes_keep_only_good_ones() -> None:
    h = Harness()
    await h.core.patch_config({"history": {"turns": 20}})
    await h.settle(1)
    h.sections["executors"].error = RuntimeError("модель не влезла")
    await h.core.patch_config({"executors": [{"id": "main", "model": "big"}]})
    await h.settle(2)
    h.sections["executors"].error = None
    await h.core.patch_config({"devices": {"a": "Кухня"}})
    await h.settle(3)
    assert [e["ok"] for e in h.applied()] == [True, False, True]
    assert len(h.store.saved) == 2
    final = h.store.saved[-1]
    assert final["history"] == {"turns": 20}
    assert final["devices"] == {"a": "Кухня"}
    assert final["executors"] == [{"id": "main", "model": "qwen"}]  # сбойное не просочилось
    assert h.sections["executors"].current == "executors:initial"
    await h.core.aclose()


async def test_failed_save_after_swap_is_reported() -> None:
    h = Harness()
    h.store.save_error = OSError("диск полон")
    await h.core.patch_config({"server": {"port": 1}, "history": {"turns": 20}})
    await h.settle(1)
    assert h.sections["history"].current == "history:{'turns': 20}"  # уже подменено
    assert h.applied() == [
        {
            "change_id": 1,
            "ok": False,
            "error": "применено, но не сохранено: диск полон",
            "sections": ["server", "history"],
        }
    ]
    assert (await h.core.status())["restart_required"] is False
    await h.core.aclose()


async def test_failing_event_sink_does_not_stop_queue() -> None:
    h = Harness()
    h.events.failures = 1
    await h.core.patch_config({"history": {"turns": 20}})
    await h.core.patch_config({"devices": {"a": "Кухня"}})
    await h.settle(2)
    assert len(h.store.saved) == 2
    assert (await h.core.status())["applying"] is False
    await h.core.aclose()


class LatestOpenWins(FakeVoices):
    """Как VoiceManager: open другого голоса перебивает прежний; голос bad не открывается."""

    def __init__(self) -> None:
        super().__init__()
        self.wanted: tuple[str, str] | None = None

    async def open(self, kind: str, voice: str, *, retry: bool) -> bool:
        self.opened.append((kind, voice, retry))
        self.wanted = (kind, voice)
        await asyncio.sleep(0.01)
        return self.wanted == (kind, voice) and voice != "bad"


async def test_restore_after_failed_voice_does_not_cancel_next_voice_change() -> None:
    store = FakeConfigStore({"tts": {"kind": "silero", "voice": "xenia"}})
    voices = LatestOpenWins()
    events = RecordingSink()
    queue = ChangeQueue(store, {}, voices=voices, events=events)
    queue.submit(1, {"tts": {"voice": "bad"}})
    queue.submit(2, {"tts": {"voice": "good"}})
    async with asyncio.timeout(1):
        while len(events.events) < 2:
            await asyncio.sleep(0)
    await asyncio.sleep(0.05)  # запоздалый возврат успел бы перебить good
    assert [data["ok"] for _, data in events.events] == [False, True]
    assert store.saved == [{"tts": {"kind": "silero", "voice": "good"}}]
    assert voices.opened == [("silero", "bad", False), ("silero", "good", False)]  # без возврата xenia
    assert voices.wanted == ("silero", "good")
    await queue.aclose()
