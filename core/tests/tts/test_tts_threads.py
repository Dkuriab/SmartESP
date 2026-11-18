"""Один TTS из двух потоков: синтез идёт по очереди, гонка образца и включения голоса."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import torch
from manager_harness import Harness, no_download, put_silero

from fakes.fake_tts import FakeTTS
from smartesp.contracts import TextToSpeech
from smartesp.tts import PiperTTS, SileroTTS, VoskTTS


class Overlap:
    """Считает одновременные вызовы модели из разных потоков."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.inside = 0
        self.most = 0

    def enter(self) -> None:
        with self._lock:
            self.inside += 1
            self.most = max(self.most, self.inside)
        time.sleep(0.05)
        with self._lock:
            self.inside -= 1


def silero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overlap: Overlap) -> TextToSpeech:
    def apply_tts(**kwargs: Any) -> torch.Tensor:
        overlap.enter()
        return torch.tensor([0.1, -0.1] * 1200)

    model = SimpleNamespace(apply_tts=apply_tts)
    monkeypatch.setattr(SileroTTS, "_load", staticmethod(lambda path: model))
    return SileroTTS(tmp_path / "v5_ru.pt", "xenia")


def vosk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overlap: Overlap) -> TextToSpeech:
    def synth_audio(text: str, **kwargs: Any) -> np.ndarray:
        overlap.enter()
        return np.array([3000, -3000] * 1200, dtype=np.int16)

    config = {"audio": {"sample_rate": 22050}, "speaker_id_map": {"female_1": 1}}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(VoskTTS, "_load", staticmethod(lambda path: SimpleNamespace(synth_audio=synth_audio)))
    return VoskTTS(tmp_path, "female_1")


def piper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overlap: Overlap) -> TextToSpeech:
    def synthesize(text: str, syn_config: object = None) -> Iterator[SimpleNamespace]:
        overlap.enter()
        yield SimpleNamespace(audio_int16_bytes=b"\x01\x00" * 1600, sample_rate=16000)

    voice = SimpleNamespace(synthesize=synthesize)
    monkeypatch.setattr("smartesp.tts.piper_tts.PiperVoice.load", lambda path: voice)
    return PiperTTS(tmp_path / "v.onnx")


async def collect(tts: TextToSpeech, text: str) -> bytes:
    return b"".join([chunk async for chunk in tts.synthesize(text, "normal")])


@pytest.mark.parametrize("make", [silero, vosk, piper])
async def test_one_instance_synthesizes_one_text_at_a_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make: Any
) -> None:
    """Образец текущим голосом во время ответа: замок внутри TTS ставит синтез в очередь."""
    overlap = Overlap()
    tts = make(monkeypatch, tmp_path, overlap)
    results = await asyncio.gather(*(collect(tts, f"Ответ номер {n}.") for n in "абв"))
    assert all(results)
    assert overlap.most == 1


def gated_builds(gated: int) -> tuple[threading.Event, Any]:
    """Фабрика TTS: сборка номер gated (с нуля) ждёт затвора."""
    gate = threading.Event()
    count = [0]

    def make() -> TextToSpeech:
        count[0] += 1
        if count[0] - 1 == gated:
            gate.wait(2)
        return FakeTTS()

    return gate, make


def cached(h: Harness) -> object:
    return h.manager._previews._entry  # pyright: ignore[reportPrivateUsage]


async def test_preview_built_after_voice_became_current_is_not_kept(tmp_path: Path) -> None:
    put_silero(tmp_path)
    gate, make = gated_builds(0)  # сборка для образца — дольше включения
    h = Harness(tmp_path, no_download, make_tts=make)
    preview = asyncio.create_task(h.manager.preview("silero", "xenia", "normal", "Привет."))
    await asyncio.sleep(0.05)
    assert await h.manager.open("silero", "xenia", retry=False) is True
    gate.set()
    assert (await preview).startswith(b"RIFF")
    assert cached(h) is None  # второй экземпляр той же модели не держим
    await h.manager.aclose()


async def test_voice_activated_after_preview_build_drops_cached_copy(tmp_path: Path) -> None:
    put_silero(tmp_path)
    gate, make = gated_builds(0)  # сборка для включения — дольше образца
    h = Harness(tmp_path, no_download, make_tts=make)
    opening = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await asyncio.sleep(0.05)
    assert (await h.manager.preview("silero", "xenia", "normal", "Привет.")).startswith(b"RIFF")
    gate.set()
    assert await opening is True
    assert h.built == [("silero", "xenia"), ("silero", "xenia")]  # собрали дважды — допустимо
    assert cached(h) is None
    await h.manager.aclose()
