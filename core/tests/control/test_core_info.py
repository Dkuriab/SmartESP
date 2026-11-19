"""Тесты пульта: сведения о ядре, просьба об остановке и выгрузка моделей из памяти Ollama."""

import asyncio

import pytest
from control_harness import Harness

from smartesp.contracts import ExecutorError, ModelNotLoadedError


async def test_info_shows_version_uptime_state_and_data_dir() -> None:
    h = Harness()
    h.now += 42.5
    assert h.core.info() == {
        "version": "1.2.3",
        "uptime_s": 42.5,
        "state": "warming",
        "data_dir": "/data/smartesp",
    }
    await h.core.aclose()


async def test_request_stop_wakes_waiter_and_is_not_restart() -> None:
    h = Harness()
    waiter = asyncio.create_task(h.core.wait_stop())
    await h.spin()
    assert not waiter.done() and h.core.stop_requested is False
    h.core.request_stop()
    h.core.request_stop()  # повторно — то же самое
    async with asyncio.timeout(1):
        await waiter
    assert h.core.stop_requested is True
    assert h.core.restart_requested is False
    await h.core.aclose()


async def test_unload_only_model_in_memory() -> None:
    h = Harness()
    h.loaded_models = ["qwen", "hf.co/a/b:Q4"]
    await h.core.unload_model("hf.co/a/b:Q4")
    assert h.unloaded == ["hf.co/a/b:Q4"]
    # не загруженную модель не трогаем: запрос с keep_alive=0 сначала загрузил бы её
    with pytest.raises(ModelNotLoadedError):
        await h.core.unload_model("llama3")
    assert h.unloaded == ["hf.co/a/b:Q4"]
    await h.core.aclose()


async def test_unload_without_ollama_raises_executor_error() -> None:
    h = Harness()
    h.loaded_models = ExecutorError("нет Ollama")
    with pytest.raises(ExecutorError):
        await h.core.unload_model("qwen")
    assert h.unloaded == []
    await h.core.aclose()
