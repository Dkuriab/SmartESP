"""Встраивает модель слова пробуждения (microWakeWord) в прошивку.

Берёт манифест .json и модель .tflite рядом с ним, пишет ModelData.cpp:
массив модели, её длину, порог, окно усреднения, размер арены и слово.
Объявления — в src/wake_word/ModelData.h.

Запуск из корня репозитория (порог 0,9 вместо 0,5 из манифеста — см. README):
    python3 tools/embed_model.py tools/models/miranda/miranda.json \\
        firmware/SmartEsp/src/wake_word/ModelData.cpp --cutoff 0.9
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BYTES_PER_LINE = 16


def render(manifest_path: Path, cutoff: float | None) -> str:
    """Текст ModelData.cpp; cutoff=None — порог из манифеста."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    micro = manifest["micro"]
    model = (manifest_path.parent / manifest["model"]).read_bytes()
    threshold = micro["probability_cutoff"] if cutoff is None else cutoff
    word = manifest["wake_word"].replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        ", ".join(f"0x{b:02x}" for b in model[i : i + BYTES_PER_LINE])
        for i in range(0, len(model), BYTES_PER_LINE)
    ]
    body = ",\n".join(f"    {line}" for line in lines)
    return (
        "// Создано tools/embed_model.py — не править руками.\n"
        f"// Модель: tools/models/{manifest_path.parent.name}/{manifest['model']}"
        f" (манифест {manifest_path.name}).\n\n"
        "// Внешнее связывание констант дают объявления extern в ModelData.h.\n"
        '#include "ModelData.h"\n\n'
        f"alignas(16) const uint8_t WAKE_MODEL_DATA[] = {{\n{body}\n}};\n\n"
        f"const size_t WAKE_MODEL_SIZE = {len(model)};\n"
        f"const float WAKE_MODEL_CUTOFF = {float(threshold)!r}f;\n"
        f"const uint8_t WAKE_MODEL_WINDOW = {int(micro['sliding_window_size'])};\n"
        f"const size_t WAKE_MODEL_ARENA_SIZE = {int(micro['tensor_arena_size'])};\n"
        f'const char WAKE_MODEL_WORD[] = "{word}";\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("manifest", type=Path, help="манифест модели (.json), .tflite лежит рядом")
    parser.add_argument("out", type=Path, help="куда записать ModelData.cpp")
    parser.add_argument("--cutoff", type=float, help="порог срабатывания 0..1 (по умолчанию — из манифеста)")
    args = parser.parse_args()
    if args.cutoff is not None and not 0 < args.cutoff < 1:
        parser.error("порог должен быть между 0 и 1")
    args.out.write_text(render(args.manifest, args.cutoff), encoding="utf-8")
    print(f"{args.out}: модель {args.manifest.name} встроена")


if __name__ == "__main__":
    main()
