"""Запуск Claude Code: аргументы, разбор ответа JSON, отмена — с поддельной программой."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from claude_tasks_mcp.runner import (
    ClaudeRunner,
    RunResult,
    build_args,
    child_env,
    find_claude,
    parse_output,
)

TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")


def _log(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))


def test_exact_argv() -> None:
    assert build_args("/bin/claude", TOOLS) == [
        "/bin/claude",
        "-p",
        "--output-format",
        "json",
        "--restricted",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--tools",
        "Read,Edit,Write,Glob,Grep",
    ]


def test_argv_protections() -> None:
    """Папка, настройки и хуки защищены флагами; опасного нет ни при каком наборе инструментов."""
    args = build_args("/bin/claude", ("Read", "Bash"))
    assert {"--restricted", "--no-session-persistence", "--strict-mcp-config"} <= set(args)
    assert args[args.index("--permission-prompts") + 1] == "none"
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert args[-2:] == ["--tools", "Read,Bash"]
    for banned in ("--allowedTools", "--allowed-tools", "--add-dir", "bypass", "dangerously"):
        assert not any(banned in a for a in args)


def test_child_env_allowlist() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/Users/x",
        "USER": "x",
        "LOGNAME": "x",
        "SHELL": "/bin/zsh",
        "TMPDIR": "/tmp/x",
        "LANG": "ru_RU.UTF-8",
        "LC_ALL": "ru_RU.UTF-8",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "s",
        "CLAUDE_CODE_MESSAGING_TOKEN": "t",
        "ANTHROPIC_API_KEY": "k",
        "ANTHROPIC_BASE_URL": "u",
        "GITHUB_TOKEN": "g",
        "MY_SECRET": "m",
        "SMARTESP_CONNECTOR_DATA": "/d",
        "CLAUDE_TASK_FOLDERS": "a=/b",
        "OTHER": "o",
    }
    assert child_env(source) == {
        "PATH": "/usr/bin",
        "HOME": "/Users/x",
        "USER": "x",
        "LOGNAME": "x",
        "SHELL": "/bin/zsh",
        "TMPDIR": "/tmp/x",
        "LANG": "ru_RU.UTF-8",
        "LC_ALL": "ru_RU.UTF-8",
    }
    passed = child_env(source, ("ANTHROPIC_API_KEY", "OTHER", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"))
    assert passed["ANTHROPIC_API_KEY"] == "k"
    assert passed["OTHER"] == "o"
    assert "CLAUDECODE" not in passed
    assert "CLAUDE_CODE_SESSION_ID" not in passed
    assert "ANTHROPIC_BASE_URL" not in passed


def test_parse_success() -> None:
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Готово."})
    assert parse_output(out.encode(), 0, b"") == RunResult(True, "Готово.")


def test_parse_permission_denials() -> None:
    denials = [{"tool_name": "Read", "tool_use_id": "1", "tool_input": {"file_path": "/etc/hosts"}}] * 2
    out = json.dumps(
        {"subtype": "success", "is_error": False, "result": "Ок.", "permission_denials": denials}
    )
    assert parse_output(out.encode(), 0, b"") == RunResult(True, "Ок.", 2)
    empty = json.dumps({"subtype": "success", "is_error": False, "result": "Ок.", "permission_denials": []})
    assert parse_output(empty.encode(), 0, b"").denials == 0


def test_parse_error_result() -> None:
    out = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Не вошла.\nЕщё."})
    assert parse_output(out.encode(), 1, b"") == RunResult(False, "Не вошла.")


def test_parse_error_subtype_without_text() -> None:
    out = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True})
    assert parse_output(out.encode(), 1, b"") == RunResult(False, "закончились шаги")


def test_parse_crash_uses_last_stderr_line() -> None:
    result = parse_output(b"", 3, b"one\nError: Invalid API key\n\n")
    assert result == RunResult(False, "Error: Invalid API key")
    assert parse_output(b"", 2, b"") == RunResult(False, "программа claude завершилась с кодом 2")


def test_parse_plain_text_success() -> None:
    assert parse_output("просто текст\n".encode(), 0, b"") == RunResult(True, "просто текст")


def test_find_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_bin: Path) -> None:
    assert find_claude(str(fake_bin)) == str(fake_bin)
    assert find_claude(str(tmp_path / "nope")) is None
    monkeypatch.setenv("PATH", str(fake_bin.parent))
    assert find_claude("") == str(fake_bin)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert find_claude("") is None


async def test_runs_in_folder_with_prompt_on_stdin(tmp_path: Path, fake_bin: Path) -> None:
    folder = tmp_path / "work"
    folder.mkdir()
    result = await ClaudeRunner(str(fake_bin), TOOLS)("почини тест", folder)
    assert result == RunResult(True, "Готово: поправила тест. Подробности ниже.")
    log = _log(tmp_path)
    assert log["cwd"] == str(folder.resolve())
    assert log["prompt"] == "почини тест"
    assert log["argv"] == build_args(str(fake_bin), TOOLS)[1:]


async def test_child_gets_only_allowed_env(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SMARTESP_CONNECTOR_DATA", "/d")
    monkeypatch.setenv("LC_CTYPE", "UTF-8")
    await ClaudeRunner(str(fake_bin), TOOLS)("x", tmp_path)
    env = _log(tmp_path)["env"]
    assert isinstance(env, dict)
    for name in ("CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "ANTHROPIC_API_KEY", "SMARTESP_CONNECTOR_DATA"):
        assert name not in env
    assert env["LC_CTYPE"] == "UTF-8"
    assert env["HOME"] == os.environ["HOME"]
    await ClaudeRunner(str(fake_bin), TOOLS, ("ANTHROPIC_API_KEY",))("x", tmp_path)
    assert _log(tmp_path)["env"]["ANTHROPIC_API_KEY"] == "k"  # type: ignore[index]


async def test_crash_and_error(tmp_path: Path, fake_bin: Path) -> None:
    runner = ClaudeRunner(str(fake_bin), TOOLS)
    (tmp_path / "mode").write_text("crash")
    assert await runner("x", tmp_path) == RunResult(False, "Error: Invalid API key")
    (tmp_path / "mode").write_text("error")
    assert await runner("x", tmp_path) == RunResult(False, "Не удалось войти.")


async def test_missing_binary(tmp_path: Path) -> None:
    result = await ClaudeRunner(str(tmp_path / "nope"), TOOLS)("x", tmp_path)
    assert result == RunResult(False, "не найдена программа claude")


async def test_cancel_kills_process(tmp_path: Path, fake_bin: Path) -> None:
    (tmp_path / "mode").write_text("sleep")
    task = asyncio.create_task(ClaudeRunner(str(fake_bin), TOOLS)("x", tmp_path))
    log: dict[str, object] = {}
    async with asyncio.timeout(10):
        while not log:
            await asyncio.sleep(0.02)
            try:
                log = _log(tmp_path)
            except (OSError, ValueError):
                pass
    pid = int(str(log["pid"]))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
