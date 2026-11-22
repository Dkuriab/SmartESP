"""Люди: реестр, запись образцов с колонки, узнавание, журнал узнаваний, модель."""

import asyncio
import json
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from fakes.fake_voiceprint import FakeVoicePrint, voice_pcm
from smartesp.contracts import (
    NothingHeardError,
    PeopleLookupError,
    RecordRefusedError,
    SpeakerModelMissingError,
    Utterance,
)
from smartesp.people import People
from smartesp.people.model import Progress


class Mic:
    """Поддельная колонка: отдаёт заданные фразы по очереди."""

    def __init__(self) -> None:
        self.queue: list[bytes | None] = []

    async def record(self, device_id: str) -> bytes | None:
        return self.queue.pop(0)


def _people(
    tmp_path: Path, mic: Mic, *, ready: bool = True, fetch: Callable[[Progress], object] | None = None
) -> tuple[People, FakeVoicePrint]:
    model = tmp_path / "models" / "m.onnx"
    if ready:
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"onnx")
    printer = FakeVoicePrint()
    people = People(
        tmp_path / "people", model, printer, fetch or (lambda progress: None), mic.record, lambda d: d == "A"
    )
    return people, printer


def _utterance(voice: int, seconds: float = 2.0) -> Utterance:
    return Utterance("A", 7, voice_pcm(voice, seconds), 0.0)


async def _enrolled(tmp_path: Path) -> tuple[People, str, str]:
    mic = Mic()
    people, _ = _people(tmp_path, mic)
    anya, danya = people.add("Аня"), people.add("Даня")
    mic.queue = [voice_pcm(1), voice_pcm(1), voice_pcm(2)]
    await people.record_sample(anya.id, "A")
    await people.record_sample(anya.id, "A")
    await people.record_sample(danya.id, "A")
    return people, anya.id, danya.id


async def test_add_rename_delete_persist(tmp_path: Path) -> None:
    people, _ = _people(tmp_path, Mic())
    anya = people.add("  Аня  ")
    assert anya.name == "Аня" and len(anya.id) == 8
    with pytest.raises(ValueError, match="уже есть"):
        people.add("аня")
    with pytest.raises(ValueError):
        people.add("a/b")
    with pytest.raises(ValueError):
        people.add("   ")
    people.rename(anya.id, "Анна")
    file = tmp_path / "people" / anya.id / "person.json"
    assert json.loads(file.read_text("utf-8"))["name"] == "Анна"
    assert stat.S_IMODE(file.stat().st_mode) == 0o600  # отпечатки — личное
    again, _ = _people(tmp_path, Mic())
    assert [p.name for p in again.people()] == ["Анна"]
    again.delete(anya.id)
    assert not file.parent.exists() and again.people() == []
    with pytest.raises(PeopleLookupError):
        again.rename(anya.id, "Х")


async def test_record_sample_keeps_print_not_audio(tmp_path: Path) -> None:
    mic = Mic()
    people, _ = _people(tmp_path, mic)
    anya = people.add("Аня")
    mic.queue = [voice_pcm(3, seconds=1.5)]
    sample = await people.record_sample(anya.id, "A")
    assert sample.seconds == 1.5 and sample.peak_db == -6.0 and sample.model == "fake-model"
    assert people.people()[0].samples == (sample,)
    files = [p.name for p in (tmp_path / "people" / anya.id).iterdir()]
    assert files == ["person.json"]  # звук не сохраняется
    people.delete_sample(anya.id, sample.id)
    assert people.people()[0].samples == ()
    with pytest.raises(PeopleLookupError):
        people.delete_sample(anya.id, sample.id)


async def test_record_sample_errors(tmp_path: Path) -> None:
    mic = Mic()
    people, _ = _people(tmp_path, mic)
    anya = people.add("Аня")
    with pytest.raises(PeopleLookupError):
        await people.record_sample("00000000", "A")
    with pytest.raises(RecordRefusedError):
        await people.record_sample(anya.id, "B")
    mic.queue = [None, voice_pcm(1, seconds=0.5)]
    with pytest.raises(NothingHeardError):
        await people.record_sample(anya.id, "A")
    with pytest.raises(NothingHeardError, match="короче секунды"):
        await people.record_sample(anya.id, "A")
    missing, _ = _people(tmp_path / "other", mic, ready=False)
    bob = missing.add("Боб")
    with pytest.raises(SpeakerModelMissingError):
        await missing.record_sample(bob.id, "A")


async def test_recognize_known_unknown_and_journal(tmp_path: Path) -> None:
    people, anya_id, _ = await _enrolled(tmp_path)
    found = await people.recognize(_utterance(1))
    assert found is not None and found.person_id == anya_id and found.name == "Аня"
    assert found.score == pytest.approx(1.0) and found.turn == 7 and found.device_id == "A"
    stranger = await people.recognize(_utterance(5))
    assert stranger is not None and stranger.person_id == "" and stranger.name == ""
    assert [r.name for r in people.recognitions()] == ["", "Аня"]  # новые первыми


async def test_recognize_skips_without_people_model_or_sound(tmp_path: Path) -> None:
    people, printer = _people(tmp_path, Mic())
    people.add("Без образцов")
    assert await people.recognize(_utterance(1)) is None  # не по кому судить
    enrolled, _, _ = await _enrolled(tmp_path / "e")
    assert await enrolled.recognize(_utterance(1, seconds=0.5)) is None  # короткая фраза
    assert printer.calls == 0


async def test_model_download_in_background(tmp_path: Path) -> None:
    model = tmp_path / "models" / "m.onnx"

    def fetch(progress: Progress) -> None:
        progress(5, 10)
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"onnx")

    people, printer = _people(tmp_path, Mic(), ready=False, fetch=fetch)
    assert not people.model_state().ready
    state = people.download_model()
    assert state.downloading and not state.ready
    for _ in range(100):
        if people.model_state().ready and printer.calls:
            break
        await asyncio.sleep(0.01)
    state = people.model_state()
    assert state.ready and not state.downloading and state.done_bytes == 5 and state.total_bytes == 10
    assert printer.calls == 1  # после скачивания модель прогревается
    await people.aclose()


async def test_model_download_error_is_reported(tmp_path: Path) -> None:
    def fetch(progress: Progress) -> None:
        raise OSError("нет сети")

    people, _ = _people(tmp_path, Mic(), ready=False, fetch=fetch)
    people.download_model()
    for _ in range(100):
        if not people.model_state().downloading:
            break
        await asyncio.sleep(0.01)
    assert people.model_state().error == "нет сети"
    await people.aclose()


async def test_warm_up_only_with_model(tmp_path: Path) -> None:
    people, printer = _people(tmp_path, Mic(), ready=False)
    await people.warm_up()
    assert printer.calls == 0
    ready, printer = _people(tmp_path / "r", Mic())
    await ready.warm_up()
    assert printer.calls == 1
