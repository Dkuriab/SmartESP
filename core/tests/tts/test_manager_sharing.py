"""Тесты менеджера голосов: общие скачивания, присоединение к открытию, повторы и образцы."""

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from manager_harness import IRINA, GatedDownload, Harness, Progress, no_download, put_irina, put_silero

from fakes.fake_tts import FakeTTS
from smartesp.contracts import VoiceNotDownloadedError
from smartesp.tts import VoiceDownloadError


async def wait_for(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 2)


async def test_same_file_is_downloaded_once(tmp_path: Path) -> None:
    gated = GatedDownload()
    h = Harness(tmp_path, gated)
    opening = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await wait_for(gated.started)
    fetching = asyncio.create_task(h.manager.download("silero", "baya"))
    await asyncio.sleep(0.05)
    gated.gate.set()
    assert await opening is True
    await fetching
    assert gated.calls == [("silero", "xenia")]
    assert {d["voice"] for d in h.kinds("voice_download")} == {"xenia"}  # ход — от начавшего
    assert {(d["voice"], d["ok"]) for d in h.kinds("voice_ready")} == {("xenia", True), ("baya", True)}
    await h.manager.aclose()


async def test_leaving_waiter_does_not_abort_shared_download(tmp_path: Path) -> None:
    gated = GatedDownload()
    h = Harness(tmp_path, gated)
    opening = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await wait_for(gated.started)
    fetching = asyncio.create_task(h.manager.download("silero", "baya"))
    await asyncio.sleep(0.05)
    fetching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fetching
    await asyncio.sleep(0.05)
    assert not gated.aborted.is_set()
    gated.gate.set()
    assert await opening is True
    assert len(gated.calls) == 1
    await h.manager.aclose()


async def test_last_waiter_leaving_aborts_download(tmp_path: Path) -> None:
    gated = GatedDownload()
    h = Harness(tmp_path, gated)
    fetching = asyncio.create_task(h.manager.download("silero", "xenia"))
    await wait_for(gated.started)
    fetching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fetching
    await wait_for(gated.aborted)
    assert not (tmp_path / "voices" / "silero" / "v5_ru.pt").exists()
    await h.manager.aclose()


async def test_failed_on_ready_does_not_make_voice_current(tmp_path: Path) -> None:
    put_irina(tmp_path)
    failures = [RuntimeError("оркестратор занят")]

    def hook(kind: str, voice: str) -> None:
        if failures:
            raise failures.pop()

    h = Harness(tmp_path, no_download, on_ready=hook)
    assert await h.manager.open("piper", IRINA, retry=False) is False
    assert h.manager.state()["state"] == "failed"
    assert not any(row["current"] for row in h.manager.catalog())
    assert await h.manager.open("piper", IRINA, retry=False) is True
    assert h.built == [("piper", IRINA)] * 2
    assert h.ready == [("piper", IRINA)]
    await h.manager.aclose()


async def test_same_voice_open_joins_running_job(tmp_path: Path) -> None:
    gated = GatedDownload()
    h = Harness(tmp_path, gated)
    first = asyncio.create_task(h.manager.open("silero", "xenia", retry=True))
    await wait_for(gated.started)
    second = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await asyncio.sleep(0.05)
    gated.gate.set()
    assert await first is True
    assert await second is True
    assert gated.calls == [("silero", "xenia")]
    assert h.ready == [("silero", "xenia")]
    await h.manager.aclose()


async def test_single_attempt_join_does_not_stop_retries(tmp_path: Path) -> None:
    gate = threading.Event()
    calls: list[int] = []

    def flaky(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        calls.append(1)
        gate.wait(2)
        if len(calls) == 1:
            raise VoiceDownloadError("нет сети")
        put_silero(home)

    h = Harness(tmp_path, flaky, retry_delays_s=(0.05,))
    first = asyncio.create_task(h.manager.open("silero", "xenia", retry=True))
    while not calls:
        await asyncio.sleep(0.01)
    second = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await asyncio.sleep(0.01)
    gate.set()
    assert await second is False  # итог ближайшей попытки
    assert await first is True  # повторы продолжились
    assert len(calls) == 2
    await h.manager.aclose()


async def test_retry_delays_follow_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def record(delay: float) -> None:
        slept.append(delay)
        await real_sleep(0)

    def flaky(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        calls.append(1)
        if len(calls) <= 4:
            raise VoiceDownloadError("нет сети")
        put_silero(home)

    monkeypatch.setattr(asyncio, "sleep", record)
    h = Harness(tmp_path, flaky, retry_delays_s=(30, 120, 300))
    assert await h.manager.open("silero", "xenia", retry=True) is True
    assert [d for d in slept if d] == [30, 120, 300, 300]
    await h.manager.aclose()


class WarmTTS(FakeTTS):
    def __init__(self) -> None:
        super().__init__()
        self.warmed = False

    async def warm_up(self) -> None:
        self.warmed = True


async def test_warm_up_is_awaited_before_on_ready(tmp_path: Path) -> None:
    put_irina(tmp_path)
    made: list[WarmTTS] = []

    def make() -> WarmTTS:
        made.append(WarmTTS())
        return made[-1]

    h = Harness(tmp_path, no_download, make_tts=make, on_ready=lambda k, v: None)
    assert await h.manager.open("piper", IRINA, retry=False) is True
    assert [t.warmed for t in made] == [True]
    await h.manager.aclose()


class SilentTTS(FakeTTS):
    async def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        for chunk in ():
            yield chunk


async def test_preview_of_silent_model_raises(tmp_path: Path) -> None:
    put_irina(tmp_path)
    h = Harness(tmp_path, no_download, make_tts=SilentTTS)
    with pytest.raises(RuntimeError, match="не озвучил"):
        await h.manager.preview("piper", IRINA, "normal", "Привет.")
    await h.manager.aclose()


async def test_preview_of_downloading_voice_is_refused(tmp_path: Path) -> None:
    gated = GatedDownload()
    h = Harness(tmp_path, gated)
    opening = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    await wait_for(gated.started)
    with pytest.raises(VoiceNotDownloadedError):
        await h.manager.preview("silero", "xenia", "normal", "Привет.")
    gated.gate.set()
    assert await opening is True
    await h.manager.aclose()
