"""Шаг «Синтетика»: фразы целей голосами ядра — synth_core.py в окружении ядра (там torch и голоса)."""

from __future__ import annotations

import json
import os
import subprocess

from . import progress
from .paths import KIT_DIR, REPO_DIR, Paths, data_home, find_target, load_targets


def run_synth(paths: Paths, target_id: str = "") -> None:
    """Синтезирует все фразы цели (или всех целей) — и «Откликаться на», и «Не откликаться на»."""
    targets = [find_target(paths, target_id)] if target_id else load_targets(paths)
    phrases = list(dict.fromkeys(p for t in targets for p in (*t.positive, *t.negative)))
    command = [
        "uv", "run", "--project", str(REPO_DIR / "core"), "python", str(KIT_DIR / "synth_core.py"),
        "--voices", str(data_home() / "voices"), "--out", str(paths.synth),
        "--phrases", json.dumps(phrases, ensure_ascii=False),
    ]  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # окружение ядра, а не набора
    progress.log(f"Синтетика: {len(phrases)} фраз — {', '.join(phrases)}")
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, env=env) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            _relay(line)
    if proc.returncode != 0:
        raise ValueError(f"синтетика не удалась (код {proc.returncode}) — см. журнал выше")
    progress.log(f"Синтетика готова: {paths.synth}")


def _relay(line: str) -> None:
    """Строку синтезатора — дальше: ход как ход, остальное — в журнал."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        if line.strip():
            progress.log(line.rstrip())
        return
    if "stage" in data:
        progress.step(str(data["stage"]), int(data["done"]), int(data["total"]))
    elif "log" in data:
        progress.log(str(data["log"]))
