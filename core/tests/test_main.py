"""Тесты связки: реестры и понятные ошибки запуска (без моделей и сервера)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from smartesp.config import TtsConfig
from smartesp.main import EXECUTOR_KINDS, STAGE_KINDS, STT_KINDS, TTS_KINDS, StartupError, _warm_up, main


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
    assert set(TTS_KINDS) == {"piper"}
    assert set(EXECUTOR_KINDS) == {"ollama"}
    assert set(STAGE_KINDS) == {"whisper_detect"}


def test_missing_voice_tells_how_to_download(tmp_path: Path) -> None:
    with pytest.raises(StartupError, match="tools/download_voice.sh ru_RU-irina-medium"):
        TTS_KINDS["piper"](TtsConfig(voice="ru_RU-irina-medium"), tmp_path)


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
        await asyncio.wait_for(_warm_up(FakeSTT(""), HangingExecutor([]), executor_timeout_s=0.05), 2)
    assert "не прогрелся" in caplog.text
