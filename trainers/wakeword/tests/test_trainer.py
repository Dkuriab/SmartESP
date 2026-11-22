"""Набор «Слово пробуждения»: выбор порога, отложенные записи, настройки обучения, обрезка тишины."""

import json
from pathlib import Path

import numpy as np

from wakeword_trainer.audio import RATE, read_wav, trim_silence, write_wav
from wakeword_trainer.evaluate import choose_cutoff, read_roc
from wakeword_trainer.features import HOLDOUT_EVERY, clip_sets
from wakeword_trainer.paths import Paths, find_target, folder_name, load_targets
from wakeword_trainer.train_config import MODEL_ARGS, training_config


def _wav(path: Path, seconds: float = 0.5) -> None:
    t = np.arange(int(RATE * seconds)) / RATE
    write_wav(path, (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16))


def test_cutoff_is_lowest_misses_within_false_limit() -> None:
    roc = [(0.5, 0.01, 3.0), (0.8, 0.05, 0.4), (0.9, 0.08, 0.1), (0.97, 0.2, 0.0)]
    assert choose_cutoff(roc) == (0.8, 0.05, 0.4)
    assert choose_cutoff([(0.5, 0.0, 9.0), (0.9, 0.3, 2.0)]) == (0.9, 0.3, 2.0)  # нет ≤ 0,5 — меньше ложных
    assert choose_cutoff([]) == (0.97, 1.0, 0.0)
    assert choose_cutoff([(0.36, 0.5, 0.3)]) == (0.97, 1.0, 0.0)  # ниже 0,5 — не ставим


def test_read_roc(tmp_path: Path) -> None:
    roc = tmp_path / "roc.txt"
    roc.write_text("AUC 0.01234\nCutoff 0.50: frr=0.0123; faph=1.250\nCutoff 0.97: frr=0.2000; faph=0.000\n")
    assert read_roc(roc) == [(0.5, 0.0123, 1.25), (0.97, 0.2, 0.0)]


def test_targets_from_owner_file_or_kit(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    assert find_target(paths, "kuzya").positive[0] == "Кузя"  # из smartesp.json набора
    (paths.kit).mkdir(parents=True)
    owner = [{"id": "kuz", "title": "Кузь", "positive": ["Кузь"], "negative": []}]
    (paths.kit / "targets.json").write_text(json.dumps(owner, ensure_ascii=False), "utf-8")
    assert [t.id for t in load_targets(paths)] == ["kuz"]
    assert folder_name(" Эй, Кузя! ") == "Эй, Кузя!"


def test_real_recordings_holdout_and_sets(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    for i in range(12):
        _wav(paths.synth / "Кузя" / f"v{i}.wav")
        _wav(paths.synth / "Кузов" / f"v{i}.wav")
    for i in range(1, 11):
        _wav(paths.recordings / "Кузя" / "Данила" / f"{i:04d}.wav")
    _wav(paths.recordings / "Вася" / "Аня" / "0001.wav")
    target = find_target(paths, "kuzya")
    sets, held = clip_sets(paths, target)
    by_name = {s.name: s for s in sets}
    assert len(held) == 10 // HOLDOUT_EVERY
    assert by_name["positive_real"].parts["testing"] == held
    assert not set(held) & set(by_name["positive_real"].parts["training"])
    assert by_name["positive_synth"].size() == 12
    assert by_name["negative_hard"].size() == 13  # синтетика «Кузов» + живая «Вася»


def test_training_config_matches_firmware_and_weights(tmp_path: Path) -> None:
    own = {"positive_synth": tmp_path / "ps", "positive_real": tmp_path / "pr"}
    config = training_config(tmp_path / "m", own, tmp_path / "neg", 2000)
    weights = {Path(str(f["features_dir"])).name: f["sampling_weight"] for f in config["features"]}  # type: ignore[union-attr]
    assert weights["pr"] > weights["ps"] and weights["dinner_party_eval"] == 0.0
    assert config["training_steps"] == [2000] and config["eval_step_interval"] == 200
    assert MODEL_ARGS[MODEL_ARGS.index("--stride") + 1] == "3"  # вход [1, 3, 40] — как в прошивке


def test_trim_silence_keeps_word_with_margins(tmp_path: Path) -> None:
    silence = np.zeros(RATE, np.int16)
    t = np.arange(RATE // 2) / RATE
    word = (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16)
    trimmed = trim_silence(np.concatenate([silence, word, silence]))
    assert RATE // 2 <= trimmed.size <= RATE // 2 + 2 * 800 + 160
    path = tmp_path / "x.wav"
    write_wav(path, word)
    assert np.array_equal(read_wav(path), word)
