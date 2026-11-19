"""Эталон признаков для host-теста wake_features_test.cpp.

Признаки считает pymicro-features==2.0.2 — тот же микрофронтенд TFLite, что
вендорен в прошивку (src/wake_word/microfrontend/), поэтому совпадение точное.
Звук: 1 с синуса 440 Гц, затем 1 с тишины; признаки — по 160 отсчётов (10 мс).

Запускается один раз, результат (tools/host_tests/data/features_ref.h) лежит в git.
pymicro-features в ядро не входит — нужен отдельный venv:
    python -m venv /tmp/mf && /tmp/mf/bin/pip install pymicro-features==2.0.2
    /tmp/mf/bin/python tools/make_features_ref.py
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from pymicro_features import MicroFrontend

SAMPLE_RATE = 16000
STEP_SAMPLES = 160
FREQUENCY = 440
AMPLITUDE = 10000
FLOAT32_SCALE = 0.0390625  # признак float = uint16 × FLOAT32_SCALE
OUT = Path(__file__).resolve().parent / "host_tests" / "data" / "features_ref.h"


def make_signal() -> list[int]:
    """1 с синуса и 1 с тишины; та же формула — в wake_features_test.cpp."""
    sine = [
        round(AMPLITUDE * math.sin(2 * math.pi * FREQUENCY * n / SAMPLE_RATE)) for n in range(SAMPLE_RATE)
    ]
    return sine + [0] * SAMPLE_RATE


def compute_features(signal: list[int]) -> list[list[int]]:
    """Кадры признаков (uint16), как их выдаёт микрофронтенд."""
    frontend = MicroFrontend()
    frames: list[list[int]] = []
    for start in range(0, len(signal) - STEP_SAMPLES + 1, STEP_SAMPLES):
        chunk = struct.pack(f"<{STEP_SAMPLES}h", *signal[start : start + STEP_SAMPLES])
        output = frontend.process_samples(chunk)
        if output.features:
            frames.append([round(value / FLOAT32_SCALE) for value in output.features])
    return frames


def render(frames: list[list[int]]) -> str:
    """Текст заголовка C++ с эталоном."""
    rows = ",\n".join("  {" + ", ".join(str(v) for v in frame) + "}" for frame in frames)
    return (
        "#pragma once\n\n"
        "// Создано tools/make_features_ref.py (pymicro-features 2.0.2). Не править руками.\n"
        "// Признаки микрофронтенда на 1 с синуса и 1 с тишины.\n\n"
        "#include <stdint.h>\n\n"
        f"constexpr int FEATURES_REF_SAMPLE_RATE = {SAMPLE_RATE};\n"
        f"constexpr int FEATURES_REF_FREQUENCY = {FREQUENCY};\n"
        f"constexpr int FEATURES_REF_AMPLITUDE = {AMPLITUDE};\n"
        f"constexpr int FEATURES_REF_FRAMES = {len(frames)};\n"
        f"constexpr int FEATURES_REF_CHANNELS = {len(frames[0])};\n\n"
        "constexpr uint16_t FEATURES_REF[FEATURES_REF_FRAMES][FEATURES_REF_CHANNELS] = {\n"
        f"{rows}\n}};\n"
    )


def main() -> None:
    frames = compute_features(make_signal())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(frames), encoding="utf-8")
    print(f"{OUT}: {len(frames)} кадров по {len(frames[0])} признаков")


if __name__ == "__main__":
    main()
