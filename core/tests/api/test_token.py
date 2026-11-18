from __future__ import annotations

import stat
from pathlib import Path

from smartesp.api import load_or_create_token


def test_creates_file_with_0600_and_reuses(tmp_path: Path) -> None:
    home = tmp_path / "data"
    first = load_or_create_token(home)
    assert len(first) >= 32
    assert stat.S_IMODE((home / "token").stat().st_mode) == 0o600
    assert load_or_create_token(home) == first


def test_strips_whitespace(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("  abc \n", encoding="utf-8")
    assert load_or_create_token(tmp_path) == "abc"


def test_empty_token_file_is_regenerated(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("  \n", encoding="utf-8")
    token = load_or_create_token(tmp_path)
    assert token
    assert (tmp_path / "token").read_text(encoding="utf-8").strip() == token
    assert stat.S_IMODE((tmp_path / "token").stat().st_mode) == 0o600
    assert load_or_create_token(tmp_path) == token
    assert [p.name for p in tmp_path.iterdir()] == ["token"]
