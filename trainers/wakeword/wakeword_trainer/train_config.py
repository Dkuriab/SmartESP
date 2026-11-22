"""Настройки обучения microWakeWord: наборы признаков с весами и архитектура (как у «Окей, Набу»)."""

from __future__ import annotations

from pathlib import Path

# (набор, правда, вес выборки, штраф, обрезка): живые записи важнее синтетики, похожие слова
# штрафуются сильнее обычной речи (повторяют настройки Миранды и Tater; см. дизайн)
OWN_SETS = {
    "positive_synth": (True, 2.0, 1.0, "truncate_start"),
    "positive_real": (True, 5.0, 1.0, "truncate_start"),
    "negative_hard": (False, 4.0, 1.25, "truncate_start"),
}
NEGATIVE_SETS = {
    "speech": (False, 10.0, 1.0, "random"),
    "dinner_party": (False, 10.0, 1.0, "random"),
    "no_speech": (False, 5.0, 1.0, "random"),
    "dinner_party_eval": (False, 0.0, 1.0, "split"),  # только для замера «ложных в час»
}
# mixednet с шагом 3: вход [1, 3, 40] — как ждёт прошивка (src/wake_word)
MODEL_ARGS = [
    "mixednet",
    "--pointwise_filters", "64,64,64,64",
    "--repeat_in_block", "1, 1, 1, 1",
    "--mixconv_kernel_sizes", "[5], [7,11], [9,15], [23]",
    "--residual_connection", "0,0,0,0",
    "--first_conv_filters", "32",
    "--first_conv_kernel_size", "5",
    "--stride", "3",
]  # fmt: skip


def _entry(folder: Path, truth: bool, weight: float, penalty: float, truncation: str) -> dict[str, object]:
    return {
        "features_dir": str(folder),
        "sampling_weight": weight,
        "penalty_weight": penalty,
        "truth": truth,
        "truncation_strategy": truncation,
        "type": "mmap",
    }


def training_config(train_dir: Path, own: dict[str, Path], negatives: Path, steps: int) -> dict[str, object]:
    """Словарь training_parameters.yaml (ключи — как в блокноте microWakeWord)."""
    features = [_entry(own[name], *OWN_SETS[name]) for name in OWN_SETS if name in own]
    features += [_entry(negatives / name, *settings) for name, settings in NEGATIVE_SETS.items()]
    return {
        "window_step_ms": 10,
        "train_dir": str(train_dir),
        "features": features,
        "training_steps": [steps],
        "positive_class_weight": [1],
        "negative_class_weight": [20],
        "learning_rates": [0.001],
        "batch_size": 128,
        "time_mask_max_size": [0],
        "time_mask_count": [0],
        "freq_mask_max_size": [0],
        "freq_mask_count": [0],
        "eval_step_interval": min(500, max(50, steps // 10)),
        "clip_duration_ms": 1500,
        "target_minimization": 0.9,
        "minimization_metric": None,
        "maximization_metric": "average_viable_recall",
    }
