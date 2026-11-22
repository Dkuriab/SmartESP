"""Обучение: наборы из trainers/, цели владельца, запись фраз с колонки."""

import json
from pathlib import Path

import pytest

from smartesp.config.connectors import REPO_DIR
from smartesp.contracts import NothingHeardError, RecordRefusedError, TrainingLookupError, TrainTarget
from smartesp.training import Training
from smartesp.training.kits import check_targets, discover

PCM = b"\x00\x10" * 8000  # 0,5 с, пик 4096 — −18 дБ


def _kit(root: Path) -> Path:
    folder = root / "trainers" / "ww"
    folder.mkdir(parents=True)
    targets = [{"id": "kuzya", "title": "Кузя", "positive": ["Кузя", "Кузьма"], "negative": ["Вася"]}]
    manifest = {"id": "ww", "title": "Слово", "record_hint": "Говори", "targets": targets}
    (folder / "smartesp.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    (root / "trainers" / "broken").mkdir()
    (root / "trainers" / "broken" / "smartesp.json").write_text("{", "utf-8")
    return root / "trainers"


def _training(tmp_path: Path, pcm: bytes | None = PCM, free: bool = True) -> tuple[Training, list[str]]:
    asked: list[str] = []

    async def record(device_id: str) -> bytes | None:
        asked.append(device_id)
        return pcm

    return Training(_kit(tmp_path), tmp_path / "data", record, lambda d: free and d == "A"), asked


def test_repo_wakeword_kit_is_valid() -> None:
    kits = {k.id: k for k in discover(REPO_DIR / "trainers")}
    targets = {t.id: t for t in kits["wakeword"].default_targets}
    assert targets["kuzya"].positive == ("Кузя", "Кузьма")
    assert "Кузя" in targets["hey_kuzya"].negative  # «Кузя» без «эй» модель «Эй, Кузя» будить не должна


async def test_record_saves_wav_and_counts_by_phrase_and_person(tmp_path: Path) -> None:
    training, asked = _training(tmp_path)
    saved = await training.record("ww", "A", " Кузя ", "Данила")
    assert (saved.name, saved.seconds, saved.peak_db) == ("0001.wav", 0.5, -18.1)
    await training.record("ww", "A", "Кузя", "Данила")
    await training.record("ww", "A", "Вася", "Аня")
    kit = training.kits()[0]
    assert [(p.phrase, p.people) for p in kit.phrases] == [
        ("Кузя", {"Данила": 2}),
        ("Кузьма", {}),
        ("Вася", {"Аня": 1}),
    ]
    assert asked == ["A", "A", "A"]
    assert [r.name for r in training.recordings("ww", "Кузя", "Данила")] == ["0001.wav", "0002.wav"]
    path = training.recording_file("ww", "Кузя", "Данила", "0002.wav")
    assert path == tmp_path / "data" / "ww" / "recordings" / "Кузя" / "Данила" / "0002.wav"
    training.delete_recording("ww", "Кузя", "Данила", "0001.wav")
    assert [r.name for r in training.recordings("ww", "Кузя", "Данила")] == ["0002.wav"]


async def test_record_errors(tmp_path: Path) -> None:
    training, _ = _training(tmp_path, pcm=None)
    with pytest.raises(NothingHeardError):
        await training.record("ww", "A", "Кузя", "Данила")
    with pytest.raises(RecordRefusedError):
        await training.record("ww", "B", "Кузя", "Данила")
    with pytest.raises(TrainingLookupError):
        await training.record("ww", "A", "Петя", "Данила")  # фразы нет в целях
    with pytest.raises(TrainingLookupError):
        await training.record("нет", "A", "Кузя", "Данила")
    with pytest.raises(ValueError):
        await training.record("ww", "A", "Кузя", "  ")
    with pytest.raises(TrainingLookupError):
        training.recording_file("ww", "Кузя", "Данила", "../../secret.wav")


def test_owner_targets_replace_defaults_and_are_checked(tmp_path: Path) -> None:
    training, _ = _training(tmp_path)
    kit = training.save_targets("ww", [TrainTarget("kuz", "Кузь", ("Кузь", "Кузь"), ("Кузь", "Кузов"))])
    assert kit.targets == (TrainTarget("kuz", "Кузь", ("Кузь",), ("Кузов",)),)  # повторы и пересечения убраны
    assert json.loads((tmp_path / "data" / "ww" / "targets.json").read_text("utf-8"))[0]["id"] == "kuz"
    assert training.kits()[0].targets[0].id == "kuz"


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [{"id": "Кузя", "positive": ["Кузя"]}],
        [{"id": "a", "positive": []}],
        [{"id": "a", "positive": ["x" * 41]}],
        [{"id": "a", "positive": ["Ку/зя"]}],
        [{"id": "a", "positive": ["a"]}, {"id": "a", "positive": ["b"]}],
    ],
)
def test_bad_targets_are_rejected(raw: object) -> None:
    with pytest.raises(ValueError):
        check_targets(raw)


async def test_install_run_sends_model_with_manifest_values(tmp_path: Path) -> None:
    installed: list[tuple[str, str, bytes, object]] = []

    async def install(device_id: str, what: str, data: bytes, meta: object) -> None:
        installed.append((device_id, what, data, meta))

    async def record(device_id: str) -> bytes | None:
        return None

    training = Training(_kit(tmp_path), tmp_path / "data", record, lambda d: False, install)  # type: ignore[arg-type]
    run = tmp_path / "data" / "ww" / "runs" / "20261122-120000-kuzya"
    run.mkdir(parents=True)
    (run / "model.tflite").write_bytes(b"TFL3")
    manifest = {
        "wake_word": "Кузя",
        "model": "model.tflite",
        "micro": {"probability_cutoff": 0.91, "sliding_window_size": 5, "tensor_arena_size": 30000},
    }
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    await training.install_run("ww", run.name, "A")
    assert installed == [
        ("A", "model", b"TFL3", {"cutoff": 0.91, "window": 5, "arena": 30000, "word": "Кузя"})
    ]
    with pytest.raises(TrainingLookupError):
        await training.install_run("ww", "нет", "A")
