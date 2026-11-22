"""Клиент ядра в хабе: обычный подпроцесс с адресом ядра в окружении, журнал, предложения, перезапуск."""

import asyncio
import sys
from pathlib import Path

from smartesp.tools import ConnectorSpec, McpHub

SCRIPT = """
import json, os, sys, time
print("старт", os.environ.get("SMARTESP_URL", "-"), os.environ["BOT_ENV"], flush=True)
sys.stderr.write("журнал в stderr\\n"); sys.stderr.flush()
suggest = {"key": "TELEGRAM_USERS", "value": "123=Аня", "text": "Написала Аня (id 123)"}
print(json.dumps({"suggest": suggest}, ensure_ascii=False), flush=True)
print(json.dumps({"suggest": suggest}, ensure_ascii=False), flush=True)  # повтор — одно предложение
time.sleep(float(sys.argv[1]))
"""


def _spec(seconds: float, enabled: bool = True) -> ConnectorSpec:
    args = ("-c", SCRIPT, str(seconds))
    return ConnectorSpec(
        "telegram", "Бот", sys.executable, args, {"BOT_ENV": "из настроек"}, enabled, "client"
    )


async def _until(check: object, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if check():  # type: ignore[operator]
            return
        await asyncio.sleep(0.05)
    raise AssertionError("не дождались")


async def test_client_runs_with_core_env_log_and_suggestions(tmp_path: Path) -> None:
    hub = McpHub(tmp_path, client_env={"SMARTESP_URL": "http://127.0.0.1:9", "SMARTESP_TOKEN": "t"})
    await hub.start([_spec(30)])
    await _until(lambda: len(hub.states()[0].suggestions) == 1 and len(hub.states()[0].log) >= 2)
    state = hub.states()[0]
    assert (state.kind, state.state, state.tools) == ("client", "ready", ())
    assert "старт http://127.0.0.1:9 из настроек" in state.log and "журнал в stderr" in state.log
    assert [(s.key, s.value, s.text) for s in state.suggestions] == [
        ("TELEGRAM_USERS", "123=Аня", "Написала Аня (id 123)")
    ]
    assert hub.specs() == []  # инструментов у клиента нет
    assert (await hub.call("anything", {}, None)).is_error
    await hub.aclose(timeout_s=2)
    assert hub.states() == []


async def test_client_that_exits_is_failed_then_restarted(tmp_path: Path) -> None:
    hub = McpHub(tmp_path, restart_delays_s=(0.2,))
    await hub.start([_spec(0)])
    await _until(lambda: hub.states()[0].state == "failed")
    assert "Завершился с кодом 0" in hub.states()[0].error
    await _until(lambda: hub.states()[0].log.count("журнал в stderr") >= 2)  # запущен снова
    await hub.aclose(timeout_s=2)


async def test_disabled_client_does_not_start(tmp_path: Path) -> None:
    hub = McpHub(tmp_path)
    await hub.start([_spec(30, enabled=False)])
    assert hub.states()[0].state == "disabled"
    await hub.aclose()
