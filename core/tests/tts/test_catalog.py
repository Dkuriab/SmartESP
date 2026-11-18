"""Тесты каталога голосов."""

from pathlib import Path

import pytest

from smartesp.tts import catalog, is_downloaded, voice_path


def test_catalog_marks_downloaded(tmp_path: Path) -> None:
    (tmp_path / "voices" / "silero").mkdir(parents=True)
    (tmp_path / "voices" / "silero" / "v5_ru.pt").write_bytes(b"x")
    (tmp_path / "voices" / "ru_RU-denis-medium.onnx").write_bytes(b"x")
    items = {(v.kind, v.voice): v for v in catalog(tmp_path)}
    for name in ("xenia", "baya", "kseniya"):
        assert items[("silero", name)].downloaded
    for name in ("female_0", "female_1", "female_2"):
        assert not items[("vosk", name)].downloaded
    assert not items[("piper", "ru_RU-irina-medium")].downloaded
    assert items[("piper", "ru_RU-denis-medium")].downloaded


def test_catalog_order(tmp_path: Path) -> None:
    kinds = [v.kind for v in catalog(tmp_path)]
    assert kinds == ["piper"] + ["silero"] * 3 + ["vosk"] * 3


def test_voice_paths(tmp_path: Path) -> None:
    v = tmp_path / "voices"
    assert voice_path("piper", "ru_RU-irina-medium", tmp_path) == v / "ru_RU-irina-medium.onnx"
    assert voice_path("silero", "xenia", tmp_path) == v / "silero" / "v5_ru.pt"
    assert voice_path("vosk", "female_2", tmp_path) == v / "vosk" / "vosk-model-tts-ru-0.9-multi"
    assert not is_downloaded("piper", "en_US-lessac-high", tmp_path)


def test_voice_path_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="xenia"):
        voice_path("silero", "aidar", tmp_path)
    with pytest.raises(ValueError):
        voice_path("espeak", "x", tmp_path)
    with pytest.raises(ValueError):
        voice_path("piper", "../evil", tmp_path)
