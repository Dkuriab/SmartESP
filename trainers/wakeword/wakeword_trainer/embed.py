"""Шаг «Встроить в прошивку»: модель прогона → firmware/SmartEsp/src/wake_word/ModelData.cpp.

Порог и окно — из манифеста прогона (их выбрал замер). Дальше — сборка (tools/build.sh, если есть
arduino-cli) и прошивка колонки по USB (Arduino IDE или arduino-cli upload — см. README).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import progress
from .paths import REPO_DIR, Paths

MODEL_DATA = REPO_DIR / "firmware" / "SmartEsp" / "src" / "wake_word" / "ModelData.cpp"


def find_run(paths: Paths, run: str) -> Path:
    """Папка прогона по имени или «last» (последний с моделью)."""
    runs = sorted(p for p in paths.runs.glob("*") if (p / "manifest.json").exists())
    if run == "last":
        if not runs:
            raise ValueError("ещё нет ни одного обученного прогона")
        return runs[-1]
    path = Path(run) if Path(run).is_absolute() else paths.runs / run
    if not (path / "manifest.json").exists():
        raise ValueError(f"нет прогона {run}")
    return path


def embed_run(paths: Paths, run: str) -> None:
    """Пишет ModelData.cpp из прогона и собирает прошивку, если есть arduino-cli."""
    folder = find_run(paths, run)
    subprocess.run(
        [
            sys.executable,
            str(REPO_DIR / "tools" / "embed_model.py"),
            str(folder / "manifest.json"),
            str(MODEL_DATA),
        ],
        check=True,
    )
    progress.log(f"Модель {folder.name} встроена: {MODEL_DATA.relative_to(REPO_DIR)}")
    if shutil.which("arduino-cli") is None:
        progress.log("arduino-cli нет — соберите и прошейте в Arduino IDE (firmware/SmartEsp/SmartEsp.ino).")
        return
    progress.log("Собираю прошивку (tools/build.sh)…")
    subprocess.run([str(REPO_DIR / "tools" / "build.sh")], check=True)
    progress.log(
        "Прошивка собрана. Прошейте колонку по USB: arduino-cli upload (см. README) или Arduino IDE."
    )
