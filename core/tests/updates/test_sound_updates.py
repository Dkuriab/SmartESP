"""Обновления по воздуху: свой звук сигнала — ссылка с сигналом, удаление без ссылки, проверка."""

from pathlib import Path

import pytest

from smartesp.contracts import UpdateRefusedError
from smartesp.updates import Updates
from smartesp.updates.service import check_file


def _updates(tmp_path: Path, accept: bool = True) -> tuple[Updates, list[tuple[str, dict[str, object]]]]:
    sent: list[tuple[str, dict[str, object]]] = []

    async def send(device_id: str, payload: dict[str, object]) -> bool:
        sent.append((device_id, payload))
        return accept

    return Updates(tmp_path / "updates", send), sent


async def test_install_sound_passes_tone_and_link(tmp_path: Path) -> None:
    updates, sent = _updates(tmp_path)
    await updates.install("A", "sound", b"\x01\x00" * 100, {"tone": "wake"})
    payload = sent[0][1]
    assert payload["what"] == "sound" and payload["tone"] == "wake" and payload["size"] == 200
    assert str(payload["path"]).startswith("/device/files/")


async def test_remove_sound_sends_size_zero_without_link(tmp_path: Path) -> None:
    updates, sent = _updates(tmp_path)
    await updates.install("A", "sound", b"", {"tone": "error"})
    assert sent == [("A", {"what": "sound", "tone": "error", "size": 0})]
    assert not (tmp_path / "updates").exists()  # файла нет — папка не нужна


async def test_sound_refused_by_old_firmware(tmp_path: Path) -> None:
    updates, _ = _updates(tmp_path, accept=False)
    with pytest.raises(UpdateRefusedError, match="0.6.0"):
        await updates.install("A", "sound", b"\x00\x00", {"tone": "wake"})


def test_check_sound() -> None:
    with pytest.raises(UpdateRefusedError):
        check_file("sound", b"\x00\x00", {"tone": "bell"})
    with pytest.raises(UpdateRefusedError):
        check_file("sound", b"\x00" * 96002, {"tone": "wake"})
    with pytest.raises(UpdateRefusedError):
        check_file("sound", b"\x00" * 3, {"tone": "wake"})
    check_file("sound", b"\x00" * 96000, {"tone": "wake"})
