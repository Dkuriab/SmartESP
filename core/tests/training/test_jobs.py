"""Шаги обучения: подпроцесс набора, ход из stdout, журнал из stderr, остановка, прогоны."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from smartesp.contracts import TrainingBusyError, TrainingLookupError
from smartesp.training import Training

SCRIPT = """
import json, sys, time
mode = sys.argv[1]
print(json.dumps({"stage": "признаки", "done": 5, "total": 10}), flush=True)
sys.stderr.write("Batch 1\\rBatch 2\\rBatch 3\\n"); sys.stderr.flush()
if mode == "slow":
    time.sleep(30)
if mode == "fail":
    print(json.dumps({"error": "нет данных"}), flush=True)
    sys.exit(1)
print(json.dumps({"log": "цель " + sys.argv[2]}), flush=True)
print(json.dumps({"result": {"recall": 0.9}}), flush=True)
"""


def _training(tmp_path: Path) -> Training:
    folder = tmp_path / "trainers" / "ww"
    folder.mkdir(parents=True)
    (folder / "step.py").write_text(SCRIPT, "utf-8")
    manifest = {
        "id": "ww",
        "title": "Слово",
        "targets": [{"id": "kuzya", "title": "Кузя", "positive": ["Кузя"]}],
        "command": [sys.executable, "{kit}/step.py"],
        "steps": [
            {"id": "train", "title": "Обучить", "per_target": True, "args": ["ok", "{target}"]},
            {"id": "fail", "title": "Ошибка", "args": ["fail", "-"]},
            {"id": "slow", "title": "Долго", "args": ["slow", "-"]},
        ],
    }
    (folder / "smartesp.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    async def record(device_id: str) -> bytes | None:
        return None

    return Training(tmp_path / "trainers", tmp_path / "data" / "training", record, lambda d: False)


async def _finished(training: Training) -> None:
    for _ in range(200):
        job = training.job("ww")
        if job is not None and job.status != "running":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("шаг не закончился")


async def test_step_progress_log_and_result(tmp_path: Path) -> None:
    training = _training(tmp_path)
    assert [s.id for s in training.kits()[0].steps] == ["train", "fail", "slow"]
    started = training.start_step("ww", "train", "kuzya")
    assert (started.status, started.target) == ("running", "kuzya")
    await _finished(training)
    job = training.job("ww")
    assert job is not None
    assert (job.status, job.stage, job.done, job.total) == ("done", "признаки", 5, 10)
    assert job.result == {"recall": 0.9}
    assert "Batch 3" in job.log and "цель kuzya" in job.log  # «\r»-ход — последним значением


async def test_failed_step_shows_error(tmp_path: Path) -> None:
    training = _training(tmp_path)
    training.start_step("ww", "fail")
    await _finished(training)
    job = training.job("ww")
    assert job is not None and (job.status, job.error) == ("failed", "нет данных")


async def test_one_step_at_a_time_and_stop(tmp_path: Path) -> None:
    training = _training(tmp_path)
    training.start_step("ww", "slow")
    with pytest.raises(TrainingBusyError):
        training.start_step("ww", "train", "kuzya")
    await asyncio.sleep(0.3)
    await training.stop_job()
    job = training.job("ww")
    assert job is not None and job.status == "cancelled"


async def test_unknown_step_or_target(tmp_path: Path) -> None:
    training = _training(tmp_path)
    with pytest.raises(TrainingLookupError):
        training.start_step("ww", "nope")
    with pytest.raises(TrainingLookupError):
        training.start_step("ww", "train", "нет")
    assert training.job("ww") is None


def test_runs_newest_first_without_roc(tmp_path: Path) -> None:
    training = _training(tmp_path)
    runs = tmp_path / "data" / "training" / "ww" / "runs"
    for name, recall in (("20261122-100000-kuzya", 0.8), ("20261122-110000-kuzya", 0.9)):
        (runs / name).mkdir(parents=True)
        (runs / name / "result.json").write_text(json.dumps({"recall": recall, "roc": [[1, 2, 3]]}), "utf-8")
    (runs / "broken").mkdir()
    (runs / "broken" / "result.json").write_text("{", "utf-8")
    assert training.runs("ww") == [
        {"recall": 0.9, "run": "20261122-110000-kuzya"},
        {"recall": 0.8, "run": "20261122-100000-kuzya"},
    ]
