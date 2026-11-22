"""Признаки для обучения: клипы цели → аугментация (шум, эхо, сдвиг) → спектрограммы в RaggedMmap.

Наборы клипов цели (в work/<цель>/features/<набор>/<часть>/clips_mmap):
- positive_synth — синтетика «Откликаться на»; positive_real — живые записи (20 % каждого человека
  отложены только для проверки: модель их не видит);
- negative_hard — «Не откликаться на»: синтетика и живые записи.
Части: training (×2, сдвиг по 10 кадров), validation, testing (как у microWakeWord).
"""

from __future__ import annotations

import random
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from mmap_ninja.ragged import RaggedMmap

from . import progress, shims
from .audio import read_wav, trim_silence
from .paths import Paths, Target, folder_name

shims.install()
from microwakeword.audio.audio_utils import generate_features_for_clip  # noqa: E402
from microwakeword.audio.augmentation import Augmentation  # noqa: E402

SPLITS = {"training": (2, 10), "validation": (1, 10), "testing": (1, 1)}  # часть → (повторы, сдвиги)
HOLDOUT_EVERY = 5  # каждая 5-я живая запись человека — только для проверки
SEED = 10


@dataclass
class ClipSet:
    """Клипы одного набора по частям: training/validation/testing → пути WAV."""

    name: str
    parts: dict[str, list[Path]]

    def size(self) -> int:
        return sum(len(v) for v in self.parts.values())


def _split(files: list[Path]) -> dict[str, list[Path]]:
    """80/10/10 случайно (с затравкой); меньше 10 файлов — всё в обучение."""
    files = sorted(files)
    random.Random(SEED).shuffle(files)
    if len(files) < 10:
        return {"training": files, "validation": [], "testing": []}
    n = max(1, len(files) // 10)
    return {"training": files[2 * n :], "validation": files[:n], "testing": files[n : 2 * n]}


def _synth(paths: Paths, phrases: tuple[str, ...]) -> list[Path]:
    return [f for p in phrases for f in sorted((paths.synth / folder_name(p)).glob("*.wav"))]


def _real(paths: Paths, phrases: tuple[str, ...]) -> list[list[Path]]:
    """Живые записи фраз — по людям (у каждого свой список)."""
    people: list[list[Path]] = []
    for phrase in phrases:
        base = paths.recordings / folder_name(phrase)
        people += [sorted(person.glob("*.wav")) for person in sorted(base.glob("*")) if person.is_dir()]
    return [files for files in people if files]


def clip_sets(paths: Paths, target: Target) -> tuple[list[ClipSet], list[Path]]:
    """Наборы клипов цели и отложенные живые записи «Откликаться на» (для проверки)."""
    held: list[Path] = []
    real_train: list[Path] = []
    for files in _real(paths, target.positive):
        held += files[HOLDOUT_EVERY - 1 :: HOLDOUT_EVERY]
        real_train += [f for f in files if f not in held]
    negatives = _synth(paths, target.negative) + [f for files in _real(paths, target.negative) for f in files]
    sets = [
        ClipSet("positive_synth", _split(_synth(paths, target.positive))),
        ClipSet("positive_real", {"training": real_train, "validation": [], "testing": held}),
        ClipSet("negative_hard", _split(negatives)),
    ]
    return [s for s in sets if s.size()], held


def augmenter(cache: Path) -> Augmentation:
    """Аугментация как в блокноте microWakeWord: слово кончается ~0,2 с до конца окна 3,2 с."""
    backgrounds = cache / "backgrounds"
    return Augmentation(
        augmentation_duration_s=3.2,
        augmentation_probabilities={
            "SevenBandParametricEQ": 0.1,
            "TanhDistortion": 0.1,
            "PitchShift": 0.1,
            "BandStopFilter": 0.1,
            "AddColorNoise": 0.1,
            "AddBackgroundNoise": 0.75,
            "Gain": 1.0,
            "RIR": 0.5,
        },
        impulse_paths=[str(backgrounds / "mit_rirs")],
        background_paths=[str(backgrounds / "fma_16k"), str(backgrounds / "audioset_16k")],
        background_min_snr_db=-5,
        background_max_snr_db=10,
        min_jitter_s=0.195,
        max_jitter_s=0.205,
    )


def _clip(path: Path) -> np.ndarray:
    """Клип: живые записи несут писк и тишину по краям — обрезаем; float для аугментации."""
    return trim_silence(read_wav(path)).astype(np.float32) / 32768.0


def _spectrograms(
    files: list[Path], aug: Augmentation, repeat: int, slide: int, stage: str
) -> Iterator[np.ndarray]:
    total, done = len(files) * repeat, 0
    for _ in range(repeat):
        for path in files:
            spectrogram = generate_features_for_clip(aug.augment_clip(_clip(path)), 10)
            length = spectrogram.shape[0] - slide + 1
            windows = np.lib.stride_tricks.sliding_window_view(spectrogram, (length, spectrogram.shape[1]))
            for i in range(slide):
                yield np.squeeze(windows[i])
            done += 1
            progress.step(stage, done, total)


def build_features(
    paths: Paths, target: Target, sets: list[ClipSet], *, reuse: bool = False
) -> dict[str, Path]:
    """Признаки всех наборов цели; {набор: папка}. Обычно — заново (записи могли добавиться);
    reuse — взять прошлые, если они есть (переобучить с другим числом шагов, не пересчитывая)."""
    root = paths.work / target.id / "features"
    if reuse and all((root / s.name).is_dir() for s in sets):
        progress.log("Признаки — прошлые (--reuse-features)")
        return {s.name: root / s.name for s in sets}
    aug = augmenter(paths.cache)
    shutil.rmtree(root, ignore_errors=True)
    dirs: dict[str, Path] = {}
    for clip_set in sets:
        for part, files in clip_set.parts.items():
            if not files:
                continue
            repeat, slide = SPLITS[part]
            out = root / clip_set.name / part / "clips_mmap"
            out.mkdir(parents=True)
            stage = f"признаки {clip_set.name}/{part}"
            RaggedMmap.from_generator(
                out_dir=out, sample_generator=_spectrograms(files, aug, repeat, slide, stage), batch_size=100
            )
        dirs[clip_set.name] = root / clip_set.name
    return dirs
