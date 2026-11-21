"""Тесты связки: реестры и понятные ошибки запуска (без моделей и сервера)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from core_harness import NO_OLLAMA, put_voice

import smartesp.main as smartesp_main
from fakes.fake_executor import FakeOllama
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from fakes.no_connectors import NO_CONNECTORS_YAML
from smartesp.config import Config, TtsConfig
from smartesp.kinds import StartupError, check_kinds
from smartesp.main import EXECUTOR_KINDS, KINDS, STAGE_KINDS, STT_KINDS, TTS_KINDS, _setup_logging, main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Папка данных во временной папке; журнал main() снимается с корневого логгера после теста."""
    monkeypatch.setenv("SMARTESP_HOME", str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    yield tmp_path
    for handler in root.handlers:
        if handler not in before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_registries_have_known_kinds() -> None:
    assert set(STT_KINDS) == {"mlx_whisper"}
    assert set(TTS_KINDS) == {"piper", "silero", "vosk"}
    assert set(EXECUTOR_KINDS) == {"ollama", "cloud"}
    assert set(STAGE_KINDS) == {"whisper_detect", "clock", "system"}


def test_ollama_kind_passes_reasoning_level() -> None:
    from smartesp.config import ExecutorConfig

    config = ExecutorConfig(id="d", name="Д", model="gpt-oss:20b", reasoning="medium")
    assert vars(EXECUTOR_KINDS["ollama"](config, Config()))["_think"] == "medium"


def test_default_voice_is_silero_xenia() -> None:
    assert Config().tts == TtsConfig(kind="silero", voice="xenia")


def test_unknown_kind_exits_with_known_kinds(home: Path) -> None:
    (home / "config.yaml").write_text("stt:\n  kind: whisperx\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="whisperx.*известные: mlx_whisper"):
        main([])
    assert (home / "logs" / "core.log").exists()


def test_broken_yaml_exits_with_message(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (home / "config.yaml").write_text("server: [\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="ошибка YAML.*config.yaml") as info:
        main([])
    assert isinstance(info.value.code, str)  # SystemExit со строкой: Python печатает её без traceback
    assert "Traceback" not in capsys.readouterr().err


def test_bad_config_exits_with_message(home: Path) -> None:
    (home / "config.yaml").write_text("executors: []\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="entry"):
        main([])


@pytest.mark.parametrize(
    ("section", "what"),
    [
        ({"tts": TtsConfig(kind="espeak")}, "tts kind='espeak'"),
        ({"stages": [{"kind": "mood"}]}, "stage kind='mood'"),
    ],
)
def test_check_kinds_rejects_unknown(section: dict[str, object], what: str) -> None:
    config = Config.model_validate({**Config().model_dump(), **section})
    with pytest.raises(StartupError, match=what):
        check_kinds(config, KINDS)


def test_check_kinds_rejects_unknown_executor() -> None:
    executors = [{"id": "d", "name": "Д", "kind": "openai", "model": "m", "entry": True}]
    with pytest.raises(StartupError, match="executor kind='openai'.*ollama"):
        check_kinds(Config.model_validate({"executors": executors}), KINDS)


ExecCall = tuple[str, list[str]]
# коннекторы выключены: тесты не запускают настоящие `uv run … -mcp`
NO_CONNECTORS_SERVER = "server:\n  host: 127.0.0.1\n  port: 0\n" + NO_CONNECTORS_YAML


def fake_core(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() на подделках: сервер на свободном порту 127.0.0.1, голос «скачан»."""
    monkeypatch.setitem(STT_KINDS, "mlx_whisper", lambda c: FakeSTT(""))
    monkeypatch.setitem(TTS_KINDS, "silero", lambda path, voice: FakeTTS())
    monkeypatch.setitem(EXECUTOR_KINDS, "ollama", lambda c, _: FakeOllama(["Да."], c.model))
    monkeypatch.setattr("smartesp.main.OLLAMA", NO_OLLAMA)
    (home / "config.yaml").write_text(NO_CONNECTORS_SERVER, encoding="utf-8")
    put_voice(home)


def run_main(argv: list[str], calls: list[ExecCall]) -> threading.Thread:
    def execv(path: str, args: list[str]) -> None:
        calls.append((path, args))

    def exit_process(code: int) -> None:
        calls.append(("exit", [str(code)]))

    kwargs = {"execv": execv, "exit_process": exit_process}
    thread = threading.Thread(target=main, args=(argv,), kwargs=kwargs, daemon=True)
    thread.start()
    return thread


def wait_run_file(home: Path, timeout: float = 10) -> dict[str, object]:
    path = home / "run" / "core.json"
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, "ядро не написало core.json"
        time.sleep(0.02)
    return json.loads(path.read_text(encoding="utf-8"))


def test_restart_request_stops_and_execs_same_command(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_core(home, monkeypatch)
    calls: list[ExecCall] = []
    thread = run_main([], calls)
    run = wait_run_file(home)
    assert run["pid"] == os.getpid()
    token = (home / "token").read_text(encoding="utf-8").strip()
    response = httpx.post(
        f"http://127.0.0.1:{run['port']}/api/v1/restart", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202
    thread.join(10)
    assert not thread.is_alive()
    assert calls[0] == (sys.executable, [sys.executable, "-m", "smartesp", *sys.argv[1:]])
    assert not (home / "run" / "core.json").exists()
    assert "Остановка: готово" in (home / "logs" / "core.log").read_text(encoding="utf-8")


class StopGate:
    """Держит честную остановку открытой, пока тест шлёт вторую просьбу; потом пускает настоящую."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = threading.Event()
        self.go = threading.Event()
        real = smartesp_main.stop

        async def gated(parts: Any) -> None:
            self.started.set()
            while not self.go.is_set():
                await asyncio.sleep(0.01)
            await real(parts)

        monkeypatch.setattr(smartesp_main, "stop", gated)


def wait_ready(base: str, headers: dict[str, str], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while httpx.get(f"{base}/status", headers=headers).json()["state"] != "ready":
        assert time.monotonic() < deadline, "ядро не прогрелось"
        time.sleep(0.02)


STOP_STEPS = ("Остановка: коннекторы остановлены", "Остановка: колонки отключены", "Остановка: готово")


@pytest.mark.parametrize(
    ("first", "second"),
    [("stop", None), ("stop", "restart"), ("restart", "stop"), ("stop", "stdin"), ("restart", "stdin")],
)
def test_stop_requests_merge_and_finish_honest_stop(
    home: Path, monkeypatch: pytest.MonkeyPatch, first: str, second: str | None
) -> None:
    """Вторая просьба во время остановки не прерывает её; остановка из API и выход важнее перезапуска."""
    fake_core(home, monkeypatch)
    executors: list[FakeOllama] = []
    monkeypatch.setitem(
        EXECUTOR_KINDS, "ollama", lambda c, _: executors.append(FakeOllama(["Да."], c.model)) or executors[-1]
    )
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(os.fdopen(read_fd, "rb")))
    gate = StopGate(monkeypatch)
    calls: list[ExecCall] = []
    thread = run_main(["--parent-watch"], calls)
    run = wait_run_file(home)
    token = (home / "token").read_text(encoding="utf-8").strip()
    base, headers = f"http://127.0.0.1:{run['port']}/api/v1", {"Authorization": f"Bearer {token}"}
    wait_ready(base, headers)
    info = httpx.get(f"{base}/core", headers=headers).json()
    assert info["data_dir"] == str(home) and info["port"] == 0  # порт из настроек
    paths = {"stop": "/core/stop", "restart": "/restart"}
    assert httpx.post(f"{base}{paths[first]}", headers=headers).status_code == 202
    assert gate.started.wait(5)
    if second == "stdin":
        os.close(write_fd)  # приложение закрылось посреди остановки
    elif second is not None:
        assert httpx.post(f"{base}{paths[second]}", headers=headers).status_code == 202
    gate.go.set()
    thread.join(10)
    assert not thread.is_alive()
    assert calls == [("exit", ["0"])]
    log = (home / "logs" / "core.log").read_text(encoding="utf-8")
    assert all(step in log for step in STOP_STEPS)
    assert "Повторная просьба" not in log
    assert executors and all(e.unloaded for e in executors)  # модели выгружены из Ollama
    assert not (home / "run" / "core.json").exists()
    if second != "stdin":
        os.close(write_fd)


def test_parent_watch_closed_stdin_stops_core(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_core(home, monkeypatch)
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(os.fdopen(read_fd, "rb")))
    calls: list[ExecCall] = []
    thread = run_main(["--parent-watch"], calls)
    wait_run_file(home)
    os.close(write_fd)
    thread.join(10)
    assert not thread.is_alive()
    assert calls == [("exit", ["0"])]  # без перезапуска; выход с кодом 0
    assert not (home / "run" / "core.json").exists()


CORE_ON_FAKES = """
import sys
from core_harness import NO_OLLAMA
from fakes.fake_executor import FakeOllama
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
import smartesp.main as m
m.STT_KINDS["mlx_whisper"] = lambda c: FakeSTT("")
m.TTS_KINDS["silero"] = lambda path, voice: FakeTTS()
m.EXECUTOR_KINDS["ollama"] = lambda c, _: FakeOllama(["Да."], c.model)
m.OLLAMA = NO_OLLAMA
m.main(sys.argv[1:])
"""


def test_sigterm_with_parent_alive_exits_zero(tmp_path: Path) -> None:
    """Так приложение останавливает ядро: stdin открыт, SIGTERM → код 0 без падения интерпретатора."""
    core_dir = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(NO_CONNECTORS_SERVER, encoding="utf-8")
    put_voice(home)
    env = {**os.environ, "SMARTESP_HOME": str(home), "PYTHONPATH": f"{core_dir}:{core_dir / 'tests'}"}
    log = (tmp_path / "out.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-c", CORE_ON_FAKES, "--parent-watch"],
        cwd=core_dir,
        env=env,
        stdin=subprocess.PIPE,  # родитель жив: stdin открыт до конца теста
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_run_file(home, timeout=60)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        assert process.stdin is not None
        process.stdin.close()
        log.close()
    output = (tmp_path / "out.log").read_text(encoding="utf-8", errors="replace")
    assert "Fatal Python error" not in output
    # с --parent-watch в консоль идут только предупреждения; полный журнал — в core.log
    assert "Остановка: готово" not in output
    assert "Остановка: готово" in (home / "logs" / "core.log").read_text(encoding="utf-8")
    assert not (home / "run" / "core.json").exists()


def test_token_in_query_is_hidden_in_log(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_core(home, monkeypatch)
    calls: list[ExecCall] = []
    thread = run_main([], calls)
    run = wait_run_file(home)
    token = (home / "token").read_text(encoding="utf-8").strip()
    base = f"http://127.0.0.1:{run['port']}"
    httpx.get(f"{base}/?token={token}&x=1")  # так интерфейс открывает приложение
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]', "1.2.3.4:5", f"/e?token={token}"
    )
    httpx.post(f"{base}/api/v1/restart", headers={"Authorization": f"Bearer {token}"})
    thread.join(10)
    text = (home / "logs" / "core.log").read_text(encoding="utf-8")
    assert token not in text
    assert "/?token=***&x=1" in text and "/e?token=***" in text


@pytest.mark.parametrize(
    ("error", "code", "logged"),
    [(SystemExit(1), 1, True), (RuntimeError("порт занят"), 1, True), (SystemExit(0), 0, False)],
)
def test_error_escaping_loop_still_ends_process(
    home: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException, code: int, logged: bool
) -> None:
    """Например, uvicorn не занял порт и сделал sys.exit(1): процесс всё равно выходит через os._exit."""
    fake_core(home, monkeypatch)

    def crash(work: Coroutine[Any, Any, bool]) -> bool:
        work.close()
        raise error

    monkeypatch.setattr("smartesp.main.run_loop", crash)
    codes: list[int] = []
    main([], exit_process=codes.append)
    assert codes == [code]
    assert ("Ядро упало" in (home / "logs" / "core.log").read_text(encoding="utf-8")) is logged


@pytest.mark.parametrize(("quiet", "console_level"), [(False, logging.NOTSET), (True, logging.WARNING)])
def test_quiet_console_keeps_full_file_log(home: Path, quiet: bool, console_level: int) -> None:
    """Под приложением (--parent-watch) в консоль только WARNING+, в core.log — всё с INFO."""
    root = logging.getLogger()
    before = list(root.handlers)
    memory = _setup_logging(home / "logs", quiet_console=quiet)
    added = [h for h in root.handlers if h not in before]
    assert memory in added and memory.level == logging.NOTSET  # журнал для интерфейса — тоже с INFO
    files = [h for h in added if isinstance(h, logging.FileHandler)]
    consoles = [h for h in added if not isinstance(h, logging.FileHandler) and h is not memory]
    assert len(files) == 1 and len(consoles) == 1
    assert files[0].level == logging.NOTSET and root.level == logging.INFO
    assert consoles[0].level == console_level
