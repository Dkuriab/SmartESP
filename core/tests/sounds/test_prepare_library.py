"""Звуки: подготовка (тишина, длина, пик, края) и библиотека назначений в папке данных."""

import io
import json
import wave
from pathlib import Path

import numpy as np

from smartesp.contracts import SoundRef
from smartesp.sounds import prepare_sound, to_wav
from smartesp.sounds.library import SoundLibrary
from smartesp.sounds.prepare import MAX_SAMPLES, PEAK


def _pcm(samples: np.ndarray) -> bytes:
    return np.round(samples * 32767).astype("<i2").tobytes()


def _tone(seconds: float, level: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * 16000)) / 16000
    return level * np.sin(2 * np.pi * 440 * t)


def test_prepare_trims_silence_normalizes_and_fades() -> None:
    sound = np.concatenate([np.zeros(8000), _tone(0.5), np.zeros(16000)])
    prepared = prepare_sound(_pcm(sound))
    assert prepared is not None and not prepared.trimmed
    out = np.frombuffer(prepared.pcm, dtype="<i2")
    assert abs(len(out) - 8000) < 50  # тишина по краям ушла
    assert abs(np.abs(out).max() / 32767 - PEAK) < 0.01
    assert abs(int(out[0])) < 50 and abs(int(out[-1])) < 50  # края без щелчка


def test_prepare_cuts_to_three_seconds() -> None:
    prepared = prepare_sound(_pcm(_tone(5.0)))
    assert prepared is not None and prepared.trimmed
    assert len(prepared.pcm) == MAX_SAMPLES * 2


def test_prepare_silence_is_none() -> None:
    assert prepare_sound(bytes(32000)) is None
    assert prepare_sound(b"") is None


def test_to_wav() -> None:
    with wave.open(io.BytesIO(to_wav(b"\x01\x00" * 160))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 160)


def test_library_per_speaker_and_copy(tmp_path: Path) -> None:
    library = SoundLibrary(tmp_path, ["A", "B"])
    bell = library.add(b"\x01\x00" * 10, "bell.mp3")
    library.assign("wake", bell, "A")
    assert library.sound("A", "wake") == bell and library.sound("B", "wake") is None
    assert library.copy("A", ["A", "B", "C"]) == ["B", "C"]
    assert library.sound("C", "wake") == bell and sorted(library.devices()) == ["A", "B", "C"]
    for device in ("A", "B", "C"):
        library.assign("wake", None, device)
    assert library.pcm(bell.sha256) is None  # ни у кого — файл удалён


def test_library_persists_and_ignores_garbage(tmp_path: Path) -> None:
    library = SoundLibrary(tmp_path)
    bell = library.add(b"\x01\x00" * 10, "bell.mp3")
    library.assign("listen", bell, "A")
    library.remember("B")
    again = SoundLibrary(tmp_path)
    assert again.sound("A", "listen") == bell and sorted(again.devices()) == ["A", "B"]
    assert again.pcm(bell.sha256) == b"\x01\x00" * 10
    assert again.pcm("../sounds") is None
    (tmp_path / "sounds.json").write_text(
        json.dumps({"devices": {"A": {"wake": {"sha256": "x"}, "bell": {}}}})
    )
    assert SoundLibrary(tmp_path).sound("A", "wake") is None
    (tmp_path / "sounds.json").write_text("{")
    assert SoundLibrary(tmp_path).devices() == []


def _old_file(tmp_path: Path, bell: SoundRef) -> None:
    """Файл прежнего вида: общий слой all и выборы колонок (null — явный встроенный)."""
    data = {"all": {"wake": vars(bell), "error": vars(bell)}, "devices": {"A": {"error": None}}}
    (tmp_path / "sounds.json").write_text(json.dumps(data))


def test_migration_moves_all_into_known_speakers(tmp_path: Path) -> None:
    bell = SoundLibrary(tmp_path).add(b"\x01\x00" * 10, "bell.mp3")
    _old_file(tmp_path, bell)
    library = SoundLibrary(tmp_path, ["B"])  # B — из настроек, A — из файла
    assert library.sound("A", "wake") == bell and library.sound("A", "error") is None  # явный встроенный
    assert library.sound("B", "wake") == bell and library.sound("B", "error") == bell
    saved = json.loads((tmp_path / "sounds.json").read_text())
    assert "all" not in saved and set(saved["devices"]) == {"A", "B"}


def test_migration_waits_for_first_known_speaker(tmp_path: Path) -> None:
    bell = SoundLibrary(tmp_path).add(b"\x01\x00" * 10, "bell.mp3")
    (tmp_path / "sounds.json").write_text(json.dumps({"all": {"wake": vars(bell)}}))
    library = SoundLibrary(tmp_path)
    assert library.devices() == [] and library.pcm(bell.sha256) is not None  # файл не потерян
    library.remember("C")
    assert library.sound("C", "wake") == bell
    assert "all" not in json.loads((tmp_path / "sounds.json").read_text())


def test_sound_ref_duration(tmp_path: Path) -> None:
    ref = SoundLibrary(tmp_path).add(bytes(32000), "x")
    assert isinstance(ref, SoundRef) and ref.duration_s == 1.0
