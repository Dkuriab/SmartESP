"""Тесты каталога голосов."""

from pathlib import Path

import pytest

from smartesp.tts import catalog, is_downloaded, voice_path


def test_catalog_marks_downloaded(tmp_path: Path) -> None:
    (tmp_path / "voices" / "silero").mkdir(parents=True)
    (tmp_path / "voices" / "silero" / "v5_ru.pt").write_bytes(b"x")
    (tmp_path / "voices" / "ru_RU-denis-medium.onnx").write_bytes(b"x")
    items = {(v.kind, v.voice): v for v in catalog(tmp_path)}
    for name in ("xenia", "baya", "kseniya", "aidar", "eugene"):
        assert items[("silero", name)].downloaded
    for name in ("female_0", "female_1", "female_2", "male_0", "male_1"):
        assert not items[("vosk", name)].downloaded
    assert not items[("piper", "ru_RU-irina-medium")].downloaded
    assert items[("piper", "ru_RU-denis-medium")].downloaded


def test_catalog_order(tmp_path: Path) -> None:
    kinds = [v.kind for v in catalog(tmp_path)]
    assert kinds == ["piper"] * 3 + ["silero"] * 5 + ["vosk"] * 5
    voices = [v.voice for v in catalog(tmp_path)]
    assert voices[3:8] == ["xenia", "baya", "kseniya", "aidar", "eugene"]  # сначала женские, затем мужские


def test_voice_paths(tmp_path: Path) -> None:
    v = tmp_path / "voices"
    assert voice_path("piper", "ru_RU-irina-medium", tmp_path) == v / "ru_RU-irina-medium.onnx"
    assert voice_path("silero", "xenia", tmp_path) == v / "silero" / "v5_ru.pt"
    assert voice_path("vosk", "female_2", tmp_path) == v / "vosk" / "vosk-model-tts-ru-0.9-multi"
    assert not is_downloaded("piper", "en_US-lessac-high", tmp_path)


def test_voice_path_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="xenia"):
        voice_path("silero", "nobody", tmp_path)
    with pytest.raises(ValueError):
        voice_path("espeak", "x", tmp_path)
    with pytest.raises(ValueError):
        voice_path("piper", "../evil", tmp_path)


def test_stray_piper_file_is_listed_and_has_path(tmp_path: Path) -> None:
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "my_voice.onnx").write_bytes(b"x")
    assert ("piper", "my_voice") in {(v.kind, v.voice) for v in catalog(tmp_path)}
    assert voice_path("piper", "my_voice", tmp_path) == tmp_path / "voices" / "my_voice.onnx"
    assert is_downloaded("piper", "my_voice", tmp_path)


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", ".hidden", ""])
def test_piper_unsafe_stem_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        voice_path("piper", name, tmp_path)
