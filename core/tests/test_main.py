"""Тесты связки: реестры и понятные ошибки запуска (без моделей и сервера)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.config import Config, TtsConfig
from smartesp.main import (
    EXECUTOR_KINDS,
    STAGE_KINDS,
    STT_KINDS,
    TTS_KINDS,
    StartupError,
    _create,
    _warm_up,
    main,
)
from smartesp.tts import VoiceUnavailableError


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


def test_create_uses_fallback_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[TtsConfig] = []
    fake = FakeTTS()

    def factory(config: TtsConfig, home: Path) -> FakeTTS:
        made.append(config)
        return fake

    monkeypatch.setattr(
        "smartesp.main.ensure_voice", lambda kind, voice, home: ("piper", "ru_RU-irina-medium")
    )
    monkeypatch.setitem(TTS_KINDS, "piper", factory)
    _, tts, _, _ = _create(Config(), tmp_path)
    assert tts is fake
    assert made == [TtsConfig(kind="piper", voice="ru_RU-irina-medium")]


def test_create_reports_no_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(kind: str, voice: str, home: Path) -> tuple[str, str]:
        raise VoiceUnavailableError("нет голоса и нет интернета")

    monkeypatch.setattr("smartesp.main.ensure_voice", fail)
    with pytest.raises(StartupError, match="нет голоса и нет интернета"):
        _create(Config(), tmp_path)


def test_unknown_kind_exits_with_known_kinds(home: Path) -> None:
    (home / "config.yaml").write_text("stt:\n  kind: whisperx\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="whisperx.*известные: mlx_whisper"):
        main()
    assert (home / "logs" / "core.log").exists()


def test_broken_yaml_exits_with_message(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (home / "config.yaml").write_text("server: [\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="ошибка YAML.*config.yaml") as info:
        main()
    assert isinstance(info.value.code, str)  # SystemExit со строкой: Python печатает её без traceback
    assert "Traceback" not in capsys.readouterr().err


def test_bad_config_exits_with_message(home: Path) -> None:
    (home / "config.yaml").write_text("executors: []\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="entry"):
        main()


class HangingExecutor(FakeExecutor):
    """Исполнитель, чей прогрев не кончается (Ollama приняла соединение и молчит)."""

    async def warm_up(self) -> None:
        await asyncio.sleep(3600)


async def test_hanging_warm_up_does_not_block_startup(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="smartesp"):
        await asyncio.wait_for(
            _warm_up(FakeSTT(""), HangingExecutor([]), FakeTTS(), executor_timeout_s=0.05), 2
        )
    assert "не прогрелся" in caplog.text


class WarmableTTS(FakeTTS):
    """TTS с прогревом; сбой прогрева задаётся флагом."""

    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail
        self.warmed = False

    async def warm_up(self) -> None:
        self.warmed = True
        if self.fail:
            raise RuntimeError("нет модели")


async def test_warm_up_warms_tts(caplog: pytest.LogCaptureFixture) -> None:
    tts = WarmableTTS()
    await _warm_up(FakeSTT(""), FakeExecutor([]), tts)
    assert tts.warmed


async def test_tts_warm_up_failure_does_not_stop_startup(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="smartesp"):
        await _warm_up(FakeSTT(""), FakeExecutor([]), WarmableTTS(fail=True))
    assert "TTS не прогрелся" in caplog.text
