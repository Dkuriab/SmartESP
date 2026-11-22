"""Итог прогона: порог по кривой «пропуски / ложные в час», проверка на отложенных живых записях,
манифест для прошивки и result.json для вкладки «Обучение»."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from . import shims
from .audio import RATE, read_wav, trim_silence
from .paths import Paths, Target, folder_name

shims.install()
from microwakeword.inference import Model  # noqa: E402

MAX_FAPH = 0.5  # ложных срабатываний в час, не больше (замер на застолье dinner_party_eval)
MIN_CUTOFF = 0.5  # ниже порог не ставим: недоученная модель будила бы колонку от всего подряд
WINDOW = 5  # окно усреднения вероятности — как в прошивке и ESPHome
ARENA = 30000  # байт: у «Миранды» той же архитектуры — 26080; прошивка добавляет свой запас
ROC_LINE = re.compile(r"Cutoff ([\d.]+): frr=([\d.]+); faph=([\d.]+)")


def read_roc(path: Path) -> list[tuple[float, float, float]]:
    """(порог, доля пропусков, ложных в час) из tflite_streaming_roc.txt."""
    if not path.exists():
        return []
    return [(float(c), float(f), float(a)) for c, f, a in ROC_LINE.findall(path.read_text("utf-8"))]


def choose_cutoff(roc: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Порог ≥ MIN_CUTOFF: наименьшие пропуски при ≤ MAX_FAPH ложных в час; не выходит — наименьшие ложные."""
    roc = [point for point in roc if point[0] >= MIN_CUTOFF]
    if not roc:
        return (0.97, 1.0, 0.0)
    viable = [point for point in roc if point[2] <= MAX_FAPH]
    if viable:
        return min(viable, key=lambda p: (p[1], -p[0]))
    return min(roc, key=lambda p: (p[2], p[1]))


def peak_probability(model: Model, path: Path) -> float:
    """Наибольшая усреднённая вероятность слова на записи (с секундой тишины до и полсекунды после)."""
    clip = trim_silence(read_wav(path))
    padded = np.concatenate([np.zeros(RATE, np.int16), clip, np.zeros(RATE // 2, np.int16)])
    probabilities = np.asarray(model.predict_clip(padded, step_ms=10), dtype=np.float32)
    if probabilities.size < WINDOW:
        return float(probabilities.max(initial=0.0))
    return float(sliding_window_view(probabilities, WINDOW).mean(axis=-1).max())


def _real_negatives(paths: Paths, target: Target) -> list[Path]:
    return [f for p in target.negative for f in sorted((paths.recordings / folder_name(p)).glob("*/*.wav"))]


def input_shape(model_path: Path) -> list[int]:
    """Форма входа модели — прошивка ждёт [1, 3, 40]."""
    from ai_edge_litert.interpreter import Interpreter

    interpreter = Interpreter(model_path=str(model_path))
    return [int(x) for x in interpreter.get_input_details()[0]["shape"]]


def summarize(
    paths: Paths,
    run: Path,
    target: Target,
    held: list[Path],
    counts: dict[str, int],
    steps: int,
    seconds: int,
) -> dict[str, object]:
    """Пишет манифест и result.json прогона; возвращает итог."""
    roc = read_roc(run / "model" / "tflite_stream_state_internal_quant" / "tflite_streaming_roc.txt")
    cutoff, frr, faph = choose_cutoff(roc)
    model = Model(str(run / "model.tflite"), stride=3)
    held_hits = sum(peak_probability(model, f) > cutoff for f in held)
    negatives = _real_negatives(paths, target)
    false_wakes = sum(peak_probability(model, f) > cutoff for f in negatives)
    manifest = {
        "type": "micro",
        "wake_word": target.title,
        "author": "SmartESP",
        "model": "model.tflite",
        "trained_languages": ["ru"],
        "version": 2,
        "micro": {
            "probability_cutoff": cutoff,
            "feature_step_size": 10,
            "sliding_window_size": WINDOW,
            "tensor_arena_size": ARENA,
            "minimum_esphome_version": "2024.7.0",
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    result: dict[str, object] = {
        "target": target.id,
        "title": target.title,
        "run": run.name,
        "steps": steps,
        "seconds": seconds,
        "clips": counts,
        "cutoff": cutoff,
        "recall": round(1 - frr, 4),  # на проверочной синтетике и отложенных живых записях
        "false_per_hour": faph,
        "real_heard": {"total": len(held), "detected": int(held_hits)},
        "real_negative": {"total": len(negatives), "false_wakes": int(false_wakes)},
        "input_shape": input_shape(run / "model.tflite"),
        "roc": [list(point) for point in roc],
    }
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    return result
