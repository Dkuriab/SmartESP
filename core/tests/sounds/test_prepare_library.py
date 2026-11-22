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


def test_library_choices_last_action_wins(tmp_path: Path) -> None:
    library = SoundLibrary(tmp_path)
    bell = library.add(b"\x01\x00" * 10, "bell.mp3")
    library.assign("wake", bell, None)
    assert library.choice("A", "wake") == ("all", bell)
    own = library.add(b"\x02\x00" * 10, "own.wav")
    library.assign("wake", own, "A")
    library.assign("error", None, "A")  # явно встроенный
    assert library.choice("A", "wake") == ("device", own)
    assert library.choice("B", "wake") == ("all", bell)
    assert library.choice("A", "error") == ("builtin", None)
    library.assign("wake", None, None)  # «для всех» сбрасывает выбор колонки
    assert library.choice("A", "wake") == ("builtin", None)
    assert library.pcm(own.sha256) is None and library.pcm(bell.sha256) is None  # ненужные удалены


def test_library_persists_and_ignores_garbage(tmp_path: Path) -> None:
    library = SoundLibrary(tmp_path)
    bell = library.add(b"\x01\x00" * 10, "bell.mp3")
    library.assign("thinking", bell, None)
    library.assign("listen", bell, "A")
    again = SoundLibrary(tmp_path)
    assert again.common()["thinking"] == bell and again.choice("A", "listen") == ("device", bell)
    assert again.pcm(bell.sha256) == b"\x01\x00" * 10
    assert again.pcm("../sounds") is None
    (tmp_path / "sounds.json").write_text(json.dumps({"all": {"wake": {"sha256": "x"}, "bell": {}}}))
    assert SoundLibrary(tmp_path).common()["wake"] is None
    (tmp_path / "sounds.json").write_text("{")
    assert SoundLibrary(tmp_path).common()["wake"] is None


def test_sound_ref_duration(tmp_path: Path) -> None:
    ref = SoundLibrary(tmp_path).add(bytes(32000), "x")
    assert isinstance(ref, SoundRef) and ref.duration_s == 1.0
