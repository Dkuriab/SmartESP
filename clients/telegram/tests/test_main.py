"""Точка входа `telegram-bot`: разбор аргументов и понятный отказ без настроек."""

from pathlib import Path

import pytest

from telegram_bot import main as entry


def test_missing_settings_exit_with_hint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        entry.main(["--settings", str(tmp_path / "settings.toml")])
    assert stop.value.code == 2
    assert "settings.example.toml" in capsys.readouterr().err


def test_valid_settings_start_polling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[telegram]\nbot_token = "42:T"\n[core]\ntoken = "c"\n[users]\n111 = "Аня"\n', encoding="utf-8"
    )
    started: list[object] = []

    async def fake_run(settings: object) -> None:
        started.append(settings)

    monkeypatch.setattr(entry, "run", fake_run)
    entry.main(["--settings", str(path)])
    assert len(started) == 1
