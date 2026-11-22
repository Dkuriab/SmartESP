"""Звуки: загрузка → подготовка → назначение → доставка (только отличия, по одному, с итогом)."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from fakes.fake_events import RecordingSink
from fakes.fake_sounds import FakeSoundTargets
from smartesp.contracts import AudioUndecodable, SoundRefusedError
from smartesp.sounds import Sounds


def _beep() -> bytes:
    t = np.arange(4000) / 16000
    return np.round(0.2 * np.sin(2 * np.pi * 600 * t) * 32767).astype("<i2").tobytes()


async def _decode(path: Path) -> AsyncGenerator[bytes]:
    data = path.read_bytes()
    if data == b"bad":
        raise AudioUndecodable("не разобрать")
    yield data


async def _upload(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def _sounds(tmp_path: Path) -> tuple[Sounds, FakeSoundTargets, RecordingSink]:
    targets = FakeSoundTargets()
    events = RecordingSink()
    return Sounds(tmp_path, _decode, targets, targets.install, events=events, timeout_s=0.2), targets, events


def _state(sounds: Sounds, device_id: str, tone: str) -> tuple[str, str]:
    device = next(d for d in sounds.overview().devices if d.device_id == device_id)
    sound = next(t for t in device.tones if t.tone == tone)
    return sound.delivery, sound.source


async def test_set_for_all_delivers_to_capable_and_skips_old(tmp_path: Path) -> None:
    sounds, targets, events = _sounds(tmp_path)
    targets.speakers = {"NEW": (True, {}), "OLD": (True, None)}
    sounds.device_connected("NEW")
    sounds.device_connected("OLD")
    result = await sounds.set_sound("wake", _upload(_beep()), "bell.mp3", None)
    await _settle()
    assert [(d, t) for d, t, _ in targets.sent] == [("NEW", "wake")]
    assert targets.sent[0][2] and len(targets.sent[0][2]) % 2 == 0
    assert _state(sounds, "NEW", "wake") == ("ok", "all")
    assert _state(sounds, "OLD", "wake") == ("unsupported", "all")
    assert sounds.wav(result.sound.sha256) is not None and not result.trimmed
    assert any(kind == "sounds" for kind, _ in events.events)
    await sounds.aclose()


async def test_connect_sends_only_differences(tmp_path: Path) -> None:
    sounds, targets, _ = _sounds(tmp_path)
    targets.speakers = {"A": (True, {})}
    sounds.device_connected("A")
    sound = (await sounds.set_sound("error", _upload(_beep()), "e.wav", None)).sound
    await _settle()
    targets.sent.clear()
    # колонка переподключилась: у неё нужный error и лишний свой attention
    targets.speakers["A"] = (True, {"error": sound.sha256, "attention": "b" * 64})
    sounds.device_connected("A")
    await _settle()
    assert [(t, d) for _, t, d in targets.sent] == [("attention", b"")]  # убрать лишний, error не трогать
    await sounds.aclose()


async def test_reset_for_one_speaker_and_failure_kept_until_retry(tmp_path: Path) -> None:
    sounds, targets, _ = _sounds(tmp_path)
    targets.speakers = {"A": (True, {}), "B": (False, None)}
    sounds.device_connected("A")
    await sounds.set_sound("thinking", _upload(_beep()), "t.ogg", None)
    await _settle()
    targets.result, targets.error = "failed", "storage"
    await sounds.reset("thinking", "A")
    await _settle()
    assert _state(sounds, "A", "thinking") == ("failed", "builtin")
    assert _state(sounds, "B", "thinking") == ("offline", "all")  # не подключалась — доставят потом
    targets.result = "done"
    sounds.resync()
    await _settle()
    assert _state(sounds, "A", "thinking") == ("ok", "builtin")
    await sounds.aclose()


async def test_no_answer_is_failure(tmp_path: Path) -> None:
    sounds, targets, _ = _sounds(tmp_path)
    targets.speakers = {"A": (True, {})}
    targets.result = None
    sounds.device_connected("A")
    await sounds.set_sound("listen", _upload(_beep()), "l.wav", None)
    await asyncio.sleep(0.3)
    device = next(d for d in sounds.overview().devices if d.device_id == "A")
    listen = next(t for t in device.tones if t.tone == "listen")
    assert listen.delivery == "failed" and listen.error == "колонка не ответила"
    await sounds.aclose()


async def test_refusals(tmp_path: Path) -> None:
    sounds, targets, _ = _sounds(tmp_path)
    targets.speakers = {"A": (True, {})}
    with pytest.raises(SoundRefusedError) as unknown:
        await sounds.set_sound("wake", _upload(_beep()), "x", "Z")
    assert unknown.value.reason == "unknown_device"
    with pytest.raises(SoundRefusedError) as bad:
        await sounds.set_sound("wake", _upload(b"bad"), "x", None)
    assert bad.value.reason == "undecodable"
    with pytest.raises(SoundRefusedError, match="нет звука"):
        await sounds.set_sound("wake", _upload(bytes(3200)), "x", "A")
    assert not list(tmp_path.glob("upload-*"))  # временные файлы убраны
    await sounds.aclose()
