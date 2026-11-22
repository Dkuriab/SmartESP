"""Обновления по воздуху: проверка файла, одноразовая ссылка, команда колонке, срок ссылки."""

import hashlib
from pathlib import Path

import pytest

from smartesp.contracts import UpdateRefusedError
from smartesp.updates import Updates
from smartesp.updates.service import TOKEN_TTL_S, check_file

FIRMWARE = bytes([0xE9]) + b"\x00" * 1023
META = {"cutoff": 0.9, "window": 5, "arena": 30000, "word": "Кузя"}


def _updates(
    tmp_path: Path, accept: bool = True
) -> tuple[Updates, list[tuple[str, dict[str, object]]], list[float]]:
    sent: list[tuple[str, dict[str, object]]] = []
    now = [0.0]

    async def send(device_id: str, payload: dict[str, object]) -> bool:
        sent.append((device_id, payload))
        return accept

    return Updates(tmp_path / "updates", send, clock=lambda: now[0]), sent, now


async def test_install_firmware_sends_link_size_and_hash(tmp_path: Path) -> None:
    updates, sent, now = _updates(tmp_path)
    await updates.install("A", "firmware", FIRMWARE)
    device, payload = sent[0]
    assert device == "A" and payload["what"] == "firmware" and payload["size"] == 1024
    assert payload["sha256"] == hashlib.sha256(FIRMWARE).hexdigest()
    token = str(payload["path"]).removeprefix("/device/files/")
    path = updates.file(token)
    assert path is not None and path.read_bytes() == FIRMWARE
    now[0] = TOKEN_TTL_S + 1
    assert updates.file(token) is None and not path.exists()  # срок вышел — файла нет


async def test_install_model_passes_meta(tmp_path: Path) -> None:
    updates, sent, _ = _updates(tmp_path)
    await updates.install("A", "model", b"tflite", META)
    assert {k: sent[0][1][k] for k in META} == META


async def test_refused_when_speaker_cannot_and_file_is_dropped(tmp_path: Path) -> None:
    updates, sent, _ = _updates(tmp_path, accept=False)
    with pytest.raises(UpdateRefusedError, match="0.5.0"):
        await updates.install("A", "firmware", FIRMWARE)
    token = str(sent[0][1]["path"]).removeprefix("/device/files/")
    assert updates.file(token) is None
    assert updates.file("подделка") is None


@pytest.mark.parametrize(
    ("what", "data", "meta"),
    [
        ("firmware", b"PK\x03\x04", None),  # не образ ESP32
        ("firmware", bytes([0xE9]) * (0x400000 + 1), None),  # больше слота прошивки
        ("model", b"", META),
        ("model", b"tflite", {"cutoff": 0.9}),  # нет окна и арены
    ],
)
def test_bad_files_are_refused(what: str, data: bytes, meta: dict[str, object] | None) -> None:
    with pytest.raises(UpdateRefusedError):
        check_file(what, data, meta)  # type: ignore[arg-type]


def test_firmware_bigger_than_old_slot_fits_new_slot() -> None:
    # слот прошивки — 4 МБ (partitions.csv); образ больше прежних 3 МБ ядро пропускает
    check_file("firmware", bytes([0xE9]) * (0x300000 + 1), None)
