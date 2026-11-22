"""Шаг «Обучить»: признаки цели → обучение microWakeWord → проверка → прогон в runs/<время>-<цель>.

В прогоне: model.tflite (потоковая int8), <цель>.json (манифест как у ESPHome — для
tools/embed_model.py), result.json (итог для вкладки «Обучение»), training_parameters.yaml, log.txt.
"""

from __future__ import annotations

import logging
import re
import runpy
import shutil
import sys
import time
from pathlib import Path

import yaml

from . import progress, shims
from .evaluate import summarize
from .features import build_features, clip_sets
from .paths import Paths, find_target
from .train_config import MODEL_ARGS, training_config

STEP = re.compile(r"Step #(\d+)")


class _StepRelay(logging.Handler):
    """Строки «Step #N» журнала microWakeWord → ход обучения."""

    def __init__(self, steps: int) -> None:
        super().__init__()
        self._steps = steps

    def emit(self, record: logging.LogRecord) -> None:
        match = STEP.search(record.getMessage())
        if match:
            progress.step("обучение", int(match.group(1)), self._steps, every_s=0)


def _run_microwakeword(config_path: Path, steps: int, log_file: Path) -> None:
    """python -m microwakeword.model_train_eval в этом же процессе; журнал — в log_file и ход."""
    shims.install()
    argv = [
        "model_train_eval", f"--training_config={config_path}", "--train", "1", "--restore_checkpoint", "0",
        "--test_tf_nonstreaming", "0", "--test_tflite_nonstreaming", "0",
        "--test_tflite_nonstreaming_quantized", "0", "--test_tflite_streaming", "0",
        "--test_tflite_streaming_quantized", "1", "--use_weights", "best_weights", *MODEL_ARGS,
    ]  # fmt: skip
    handler = logging.FileHandler(log_file, encoding="utf-8")
    relay = _StepRelay(steps)
    root = logging.getLogger()
    root.addHandler(handler)
    root.addHandler(relay)
    old_argv = sys.argv
    sys.argv = argv
    try:
        runpy.run_module("microwakeword.model_train_eval", run_name="__main__")
    except SystemExit as stop:
        if stop.code not in (0, None):
            raise ValueError(f"обучение прервалось (код {stop.code}) — см. {log_file}") from stop
    finally:
        sys.argv = old_argv
        root.removeHandler(handler)
        root.removeHandler(relay)


def train_target(paths: Paths, target_id: str, steps: int = 10000, *, reuse_features: bool = False) -> Path:
    """Обучает модель цели; возвращает папку прогона."""
    target = find_target(paths, target_id)
    negatives = paths.cache / "negatives"
    if not (negatives / "speech" / ".done").exists():
        raise ValueError("нет скачанных данных — сначала шаг «Скачать данные» (wakeword download)")
    sets, held = clip_sets(paths, target)
    if not any(s.name == "positive_synth" for s in sets):
        raise ValueError(f"нет синтетики для «{target.title}» — сначала шаг «Синтетика» (wakeword synth)")
    counts = {s.name: s.size() for s in sets}
    progress.log(f"Цель «{target.title}»: клипов {counts}, отложено живых для проверки: {len(held)}")
    own = build_features(paths, target, sets, reuse=reuse_features)
    run = paths.runs / f"{time.strftime('%Y%m%d-%H%M%S')}-{target.id}"
    model_dir = run / "model"  # папку модели создаёт сам microWakeWord (существующую он не трогает)
    run.mkdir(parents=True)
    config_path = run / "training_parameters.yaml"
    config_path.write_text(
        yaml.safe_dump(training_config(model_dir, own, negatives, steps), allow_unicode=True), "utf-8"
    )
    started = time.monotonic()
    _run_microwakeword(config_path, steps, run / "log.txt")
    tflite = model_dir / "tflite_stream_state_internal_quant" / "stream_state_internal_quant.tflite"
    if not tflite.exists():
        raise ValueError(f"модель не получилась — см. {run / 'log.txt'}")
    shutil.copy(tflite, run / "model.tflite")
    summary = summarize(paths, run, target, held, counts, steps, round(time.monotonic() - started))
    progress.result(summary)
    return run
