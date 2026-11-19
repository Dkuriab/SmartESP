"""Тесты tools/make_sounds.py.

Запуск из корня репозитория:
    uv run --project core pytest tools/test_make_sounds.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sounds  # noqa: E402

NAMES = ["wake", "listen", "thinking", "error", "attention"]
RATE = 16000


def test_all_sounds_exist_and_short():
    for name in NAMES:
        pcm = make_sounds.render(name)
        assert pcm.dtype == np.int16
        assert 0 < len(pcm) <= int(0.6 * RATE), name
    assert len(make_sounds.render("thinking")) <= int(0.35 * RATE)


def test_no_clicks():
    for name in NAMES:
        pcm = make_sounds.render(name).astype(int)
        assert np.abs(pcm[:16]).max() <= 64, name
        assert np.abs(pcm[-16:]).max() <= 64, name


def test_peak_below_full_scale():
    for name in NAMES:
        pcm = make_sounds.render(name).astype(int)
        assert 0 < np.abs(pcm).max() <= 0.5 * 32767, name


def test_listen_equals_wake():
    assert np.array_equal(make_sounds.render("listen"), make_sounds.render("wake"))


def test_cpp_written(tmp_path):
    out = tmp_path / "SoundData.cpp"
    make_sounds.write_cpp(out)
    text = out.read_text(encoding="utf-8")
    for name in NAMES:
        up = name.upper()
        assert f"const int16_t SOUND_{up}[]" in text
        assert f"const size_t SOUND_{up}_LEN = {len(make_sounds.render(name))};" in text
    out2 = tmp_path / "again.cpp"
    make_sounds.write_cpp(out2)
    assert out2.read_text(encoding="utf-8") == text
