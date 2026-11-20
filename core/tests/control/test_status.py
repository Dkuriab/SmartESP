"""Тесты сводки пульта, состояния ядра, перезапуска и голосов."""

import asyncio

import pytest
from control_harness import Harness

import smartesp.control.ollama as ollama_module
from smartesp.contracts import ChangeResult, ConnectorState, CorePort, DeviceInfo, ExecutorError
from smartesp.control import RESTART_SECTIONS


async def test_status_collects_summary() -> None:
    h = Harness()
    h.device_list = [DeviceInfo("aa", "Кухня", True, "192.168.1.5", "1.0", 50.0, 3)]
    h.now = 112.5
    status = await h.core.status()
    assert status == {
        "version": "1.2.3",
        "uptime_s": 12.5,
        "state": "warming",
        "ollama": {"reachable": True, "loaded": ["qwen"]},
        "devices": [
            {
                "device_id": "aa",
                "name": "Кухня",
                "connected": True,
                "remote": "192.168.1.5",
                "fw": "1.0",
                "last_seen": 50.0,
                "protocol": 3,
            }
        ],
        "voice": {"kind": "silero", "voice": "xenia", "state": "ready", "error": None},
        "applying": False,
        "restart_required": False,
        "executors": [],
        "connectors": [],
    }
    await h.core.aclose()


async def test_status_and_list_show_connectors() -> None:
    h = Harness()
    h.connector_states = [
        ConnectorState("notes", "Заметки", "ready", ("note_add", "note_show")),
        ConnectorState("weather", "Погода", "failed", (), "Процесс коннектора завершился."),
    ]
    expected = [
        {"id": "notes", "name": "Заметки", "state": "ready", "tools": ["note_add", "note_show"], "error": ""},
        {
            "id": "weather",
            "name": "Погода",
            "state": "failed",
            "tools": [],
            "error": "Процесс коннектора завершился.",
        },
    ]
    assert (await h.core.status())["connectors"] == expected
    assert h.core.connectors() == [{**item, "settings": []} for item in expected]
    await h.core.aclose()


async def test_connector_list_has_declared_settings() -> None:
    h = Harness()
    h.connector_states = [ConnectorState("weather", "Погода", "ready", ("weather_now",))]
    city = {"key": "WEATHER_PLACE", "title": "Город", "type": "text", "hint": "", "value": "Тверь"}
    h.store.settings = {"weather": [city]}
    assert h.core.connectors()[0]["settings"] == [city]
    assert "settings" not in (await h.core.status())["connectors"][0]  # сводку опрашивают часто
    await h.core.aclose()


async def test_status_lists_member_warm_up_results() -> None:
    h = Harness()
    h.executor_states = {"big": None, "coder": "нет модели coder"}
    assert (await h.core.status())["executors"] == [
        {"id": "big", "ready": True, "error": None},
        {"id": "coder", "ready": False, "error": "нет модели coder"},
    ]
    await h.core.aclose()


async def test_status_marks_ollama_unreachable_on_error() -> None:
    h = Harness()
    h.loaded_models = ExecutorError("нет сервера")
    assert (await h.core.status())["ollama"] == {"reachable": False, "loaded": []}
    await h.core.aclose()


async def test_status_survives_unexpected_ollama_error() -> None:
    h = Harness()
    h.loaded_models = OSError("соединение сброшено")
    assert (await h.core.status())["ollama"] == {"reachable": False, "loaded": []}
    await h.core.aclose()


async def test_status_does_not_wait_for_hung_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_module, "OLLAMA_TIMEOUT_S", 0.01)
    h = Harness()
    h.loaded_gate = asyncio.Event()  # никогда не откроется
    assert (await h.core.status())["ollama"] == {"reachable": False, "loaded": []}
    await h.core.aclose()


async def test_set_state_publishes_and_shows_in_status() -> None:
    h = Harness()
    h.core.set_state("ready")
    assert h.core.state == "ready"
    assert h.events.events == [("core_state", {"state": "ready"})]
    assert (await h.core.status())["state"] == "ready"
    with pytest.raises(ValueError):
        h.core.set_state("sleeping")
    await h.core.aclose()


async def test_request_restart_wakes_waiter() -> None:
    h = Harness()
    waiter = asyncio.create_task(h.core.wait_restart())
    await h.spin()
    assert not waiter.done()
    assert h.core.restart_requested is False
    h.core.request_restart()
    async with asyncio.timeout(1):
        await waiter
    assert h.core.restart_requested is True
    await h.core.aclose()


async def test_config_lists_effective_overridden_and_restart_sections() -> None:
    h = Harness()
    await h.core.patch_config({"history": {"turns": 4}})
    await h.settle(1)
    config = h.core.config()
    assert config["effective"]["history"] == {"turns": 4}
    assert config["overridden"] == ["history"]
    assert config["restart_sections"] == ["server", "stt", "arbitration"]
    assert RESTART_SECTIONS == ("server", "stt", "arbitration")
    assert config["dispatcher_prompt"] == "Промпт. Правила."
    assert config["executor_prompts"] == {"dispatcher": "Промпт. Правила.", "big": "Большой."}
    await h.core.aclose()


async def test_config_reads_dispatcher_prompt_on_every_call() -> None:
    h = Harness()
    h.prompt = "Новый промпт."
    assert h.core.config()["dispatcher_prompt"] == "Новый промпт."
    await h.core.aclose()


async def test_models_in_api_shape_and_errors_propagate() -> None:
    h = Harness()
    h.model_list = [("qwen", 5_000), ("old", 7)]
    assert await h.core.models() == [
        {"name": "qwen", "size_bytes": 5_000, "supports_tools": True},
        {"name": "old", "size_bytes": 7, "supports_tools": False},
    ]
    h.model_list = ExecutorError("нет сервера")
    with pytest.raises(ExecutorError):
        await h.core.models()
    await h.core.aclose()


async def test_voices_preview_and_turns_pass_through() -> None:
    h = Harness()
    h.voices.voice_catalog = [{"kind": "silero", "voice": "xenia", "current": True}]
    assert h.core.voices() == h.voices.voice_catalog
    assert await h.core.preview("silero", "xenia", "quiet", "Привет") == "silero/xenia/quiet/Привет".encode()
    h.bus.publish("turn_finished", {"turn_id": 1})
    h.bus.publish("turn_finished", {"turn_id": 2})
    assert h.core.turns(1) == [{"turn_id": 2}]
    await h.core.aclose()


async def test_download_voice_runs_in_background() -> None:
    h = Harness()
    await h.core.patch_config({"history": {"turns": 4}})  # номер 1
    h.voices.download_gate = asyncio.Event()
    result = await h.core.download_voice("vosk", "female_1")
    assert result == ChangeResult(2, "accepted")
    assert h.voices.downloaded == []  # ответ не ждёт скачивания
    h.voices.download_gate.set()
    await h.spin()
    assert h.voices.downloaded == [("vosk", "female_1")]
    await h.core.aclose()


async def test_failed_download_is_swallowed() -> None:
    h = Harness()
    h.voices.download_error = RuntimeError("нет сети")
    await h.core.download_voice("vosk", "female_1")
    await h.spin()
    assert h.voices.downloaded == [("vosk", "female_1")]
    await h.core.aclose()


async def test_aclose_cancels_pending_download() -> None:
    h = Harness()
    h.voices.download_gate = asyncio.Event()  # не откроется
    await h.core.download_voice("vosk", "female_1")
    await h.spin()
    async with asyncio.timeout(1):
        await h.core.aclose()
    assert h.voices.downloaded == []


async def test_core_satisfies_core_port() -> None:
    h = Harness()
    port: CorePort = h.core
    assert (await port.status())["version"] == "1.2.3"
    await h.core.aclose()
