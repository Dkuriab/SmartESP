"""Запуск Claude Code: аргументы, разбор ответа JSON, отмена — с поддельной программой."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from claude_tasks_mcp.runner import ClaudeRunner, RunResult, build_args, find_claude, parse_output

TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")


def _log(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))


def test_args_are_safe() -> None:
    args = build_args("/bin/claude", TOOLS)
    assert args[:2] == ["/bin/claude", "-p"]
    joined = " ".join(args)
    assert "--output-format json" in joined
    assert "--permission-mode acceptEdits" in joined
    assert "--tools=Read,Edit,Write,Glob,Grep" in args
    assert "--allowedTools=Read,Edit,Write,Glob,Grep" in args
    assert "--strict-mcp-config" in args
    assert "dangerously" not in joined
    assert "Bash" not in joined


def test_parse_success() -> None:
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Готово."})
    assert parse_output(out.encode(), 0, b"") == RunResult(True, "Готово.")


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
    assert "--permission-mode" in log["argv"]  # type: ignore[operator]


async def test_crash_and_error(tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = ClaudeRunner(str(fake_bin), TOOLS)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "crash")
    assert await runner("x", tmp_path) == RunResult(False, "Error: Invalid API key")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "error")
    assert await runner("x", tmp_path) == RunResult(False, "Не удалось войти.")


async def test_missing_binary(tmp_path: Path) -> None:
    result = await ClaudeRunner(str(tmp_path / "nope"), TOOLS)("x", tmp_path)
    assert result == RunResult(False, "не найдена программа claude")


async def test_cancel_kills_process(tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
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
