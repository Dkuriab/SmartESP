"""Тесты связки: реестры и понятные ошибки запуска (без моделей и сервера)."""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from core_harness import NO_OLLAMA, put_voice

from fakes.fake_executor import FakeOllama
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.config import Config, TtsConfig
from smartesp.main import EXECUTOR_KINDS, KINDS, STAGE_KINDS, STT_KINDS, TTS_KINDS, main
from smartesp.wiring import StartupError, check_kinds


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
    assert set(EXECUTOR_KINDS) == {"ollama"}
    assert set(STAGE_KINDS) == {"whisper_detect"}


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


def fake_core(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() на подделках: сервер на свободном порту 127.0.0.1, голос «скачан»."""
    monkeypatch.setitem(STT_KINDS, "mlx_whisper", lambda c: FakeSTT(""))
    monkeypatch.setitem(TTS_KINDS, "silero", lambda path, voice: FakeTTS())
    monkeypatch.setitem(EXECUTOR_KINDS, "ollama", lambda c: FakeOllama(["Да."], c.model))
    monkeypatch.setattr("smartesp.main.OLLAMA", NO_OLLAMA)
    (home / "config.yaml").write_text("server:\n  host: 127.0.0.1\n  port: 0\n", encoding="utf-8")
    put_voice(home)


def run_main(argv: list[str], calls: list[ExecCall]) -> threading.Thread:
    def execv(path: str, args: list[str]) -> None:
        calls.append((path, args))

    thread = threading.Thread(target=main, args=(argv,), kwargs={"execv": execv}, daemon=True)
    thread.start()
    return thread


def wait_run_file(home: Path) -> dict[str, object]:
    path = home / "run" / "core.json"
    deadline = time.monotonic() + 10
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
    assert calls == [(sys.executable, [sys.executable, "-m", "smartesp", *sys.argv[1:]])]
    assert not (home / "run" / "core.json").exists()
    assert "Остановка: готово" in (home / "logs" / "core.log").read_text(encoding="utf-8")


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
    assert calls == []
    assert not (home / "run" / "core.json").exists()
