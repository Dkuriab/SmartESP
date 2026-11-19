"""Настройки из окружения: папки, инструменты Claude Code, предел времени, программа."""

from pathlib import Path

import pytest

from claude_tasks_mcp.settings import DEFAULT_TIMEOUT_S, DEFAULT_TOOLS, load_settings


def test_defaults_without_variables() -> None:
    settings = load_settings({})
    assert settings.folders == ()
    assert settings.tools == DEFAULT_TOOLS == ("Read", "Edit", "Write", "Glob", "Grep")
    assert settings.timeout_s == DEFAULT_TIMEOUT_S == 30 * 60
    assert settings.claude_bin == ""
    assert settings.env_passthrough == ()


def test_folders_are_parsed_in_order_and_resolved(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "b")
    raw = f" smartesp = {tmp_path}/a ; ; дом={tmp_path}/link;плохо;=/x;smartesp={tmp_path}"
    settings = load_settings({"CLAUDE_TASK_FOLDERS": raw})
    real = tmp_path.resolve()
    assert settings.folders == (("smartesp", real / "a"), ("дом", real / "b"))


def test_tools_timeout_and_binary() -> None:
    settings = load_settings(
        {
            "CLAUDE_TASK_TOOLS": " Read , Grep ",
            "CLAUDE_TASK_TIMEOUT_MIN": "1,5",
            "CLAUDE_BIN": "/opt/claude",
            "CLAUDE_TASK_ENV": "ANTHROPIC_API_KEY, ,HTTPS_PROXY",
        }
    )
    assert settings.env_passthrough == ("ANTHROPIC_API_KEY", "HTTPS_PROXY")
    assert settings.tools == ("Read", "Grep")
    assert settings.timeout_s == 90
    assert settings.claude_bin == "/opt/claude"


def test_bad_timeout_falls_back_to_default() -> None:
    for raw in ("abc", "0", "-5"):
        assert load_settings({"CLAUDE_TASK_TIMEOUT_MIN": raw}).timeout_s == DEFAULT_TIMEOUT_S


def test_any_tool_beyond_file_tools_warns(caplog: pytest.LogCaptureFixture) -> None:
    settings = load_settings({"CLAUDE_TASK_TOOLS": "Read, Bash, Monitor, CronCreate"})
    assert settings.tools == ("Read", "Bash", "Monitor", "CronCreate")
    assert "Bash, Monitor, CronCreate" in caplog.text


def test_default_file_tools_do_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    load_settings({"CLAUDE_TASK_TOOLS": "Read,Edit,Write,Glob,Grep"})
    load_settings({})
    assert "CLAUDE_TASK_TOOLS" not in caplog.text
