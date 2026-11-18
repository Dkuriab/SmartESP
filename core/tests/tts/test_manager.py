"""Тесты менеджера голосов: подделки фабрик и скачивания, без сети и моделей."""

import asyncio
import io
import threading
import wave
from pathlib import Path

import pytest
from manager_harness import IRINA, Harness, Progress, no_download, put_irina, put_silero, silero_download

from smartesp.contracts import TextToSpeech, VoiceNotDownloadedError
from smartesp.tts import VoiceDownloadError, VoiceManager


async def test_downloaded_voice_is_ready_at_once(tmp_path: Path) -> None:
    put_irina(tmp_path)
    h = Harness(tmp_path, no_download)
    assert await h.manager.open("piper", IRINA, retry=False) is True
    assert h.ready == [("piper", IRINA)]
    assert h.manager.state() == {"kind": "piper", "voice": IRINA, "state": "ready", "error": None}
    # повторное открытие того же голоса ничего не пересобирает
    assert await h.manager.open("piper", IRINA, retry=False) is True
    assert h.built == [("piper", IRINA)]
    await h.manager.aclose()


async def test_missing_voice_falls_back_then_switches(tmp_path: Path) -> None:
    put_irina(tmp_path)
    h = Harness(tmp_path, silero_download)
    assert await h.manager.open("silero", "xenia", retry=True) is True
    assert h.ready == [("piper", IRINA), ("silero", "xenia")]
    progress = h.kinds("voice_download")
    assert progress[0] == {"kind": "silero", "voice": "xenia", "done": 0, "total": None}
    assert progress[-1] == {"kind": "silero", "voice": "xenia", "done": 1000, "total": 1000}
    assert len(progress) <= 102  # не чаще одного события на процент
    assert h.kinds("voice_ready") == [{"kind": "silero", "voice": "xenia", "ok": True, "error": None}]
    assert h.manager.state()["state"] == "ready"
    await h.manager.aclose()


async def test_retries_until_download_succeeds(tmp_path: Path) -> None:
    calls: list[int] = []
    states: list[object] = []
    h: Harness

    def flaky(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        calls.append(1)
        states.append(h.manager.state()["state"])
        if len(calls) < 3:
            raise VoiceDownloadError("нет сети")
        put_silero(home)

    h = Harness(tmp_path, flaky, retry_delays_s=(0.01,))
    assert await h.manager.open("silero", "xenia", retry=True) is True
    assert len(calls) == 3
    assert states == ["downloading"] * 3
    assert h.ready == [("silero", "xenia")]
    assert h.manager.state() == {"kind": "silero", "voice": "xenia", "state": "ready", "error": None}
    await h.manager.aclose()


async def test_no_retry_reports_failure(tmp_path: Path) -> None:
    put_irina(tmp_path)

    def broken(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        raise VoiceDownloadError("нет сети")

    h = Harness(tmp_path, broken)
    assert await h.manager.open("silero", "xenia", retry=False) is False
    assert ("silero", "xenia") not in h.ready
    state = h.manager.state()
    assert state["state"] == "failed"
    assert "нет сети" in str(state["error"])
    assert h.kinds("voice_ready") == [{"kind": "silero", "voice": "xenia", "ok": False, "error": "нет сети"}]
    await h.manager.aclose()


async def test_build_failure_is_reported_not_raised(tmp_path: Path) -> None:
    put_irina(tmp_path)
    ready: list[str] = []

    def boom(path: Path, voice: str) -> TextToSpeech:
        raise RuntimeError("модель битая")

    manager = VoiceManager(tmp_path, {"piper": boom}, lambda tts, k, v: ready.append(v), download=no_download)
    assert await manager.open("piper", IRINA, retry=False) is False
    assert manager.state()["state"] == "failed"
    assert "модель битая" in str(manager.state()["error"])
    assert ready == []
    await manager.aclose()


async def test_unknown_voice_fails_without_retry(tmp_path: Path) -> None:
    h = Harness(tmp_path, no_download)
    assert await h.manager.open("silero", "nobody", retry=True) is False
    assert h.manager.state()["state"] == "failed"
    await h.manager.aclose()


async def test_new_open_cancels_previous_download(tmp_path: Path) -> None:
    put_irina(tmp_path)
    started, aborted = threading.Event(), threading.Event()

    def endless(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        assert progress is not None
        started.set()
        try:
            for i in range(500):
                progress(i, None)
                threading.Event().wait(0.01)
        except Exception:
            aborted.set()
            raise
        put_silero(home)

    h = Harness(tmp_path, endless)
    first = asyncio.create_task(h.manager.open("silero", "xenia", retry=True))
    assert await asyncio.to_thread(started.wait, 2)
    assert await h.manager.open("piper", IRINA, retry=False) is True
    assert await first is False
    assert await asyncio.to_thread(aborted.wait, 2)
    assert ("silero", "xenia") not in h.ready
    assert h.manager.state()["voice"] == IRINA
    await h.manager.aclose()


async def test_download_only_fetches(tmp_path: Path) -> None:
    put_irina(tmp_path)
    h = Harness(tmp_path, silero_download)
    await h.manager.open("piper", IRINA, retry=False)
    await h.manager.download("silero", "xenia")
    assert h.ready == [("piper", IRINA)]
    assert (tmp_path / "voices" / "silero" / "v5_ru.pt").exists()
    assert h.kinds("voice_ready")[-1]["ok"] is True
    await h.manager.aclose()


async def test_download_failure_raises(tmp_path: Path) -> None:
    def broken(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        raise VoiceDownloadError("нет сети")

    h = Harness(tmp_path, broken)
    with pytest.raises(VoiceDownloadError):
        await h.manager.download("silero", "xenia")
    assert h.kinds("voice_ready") == [{"kind": "silero", "voice": "xenia", "ok": False, "error": "нет сети"}]
    await h.manager.aclose()


async def test_download_of_unknown_voice_reports_failure(tmp_path: Path) -> None:
    h = Harness(tmp_path, no_download)
    with pytest.raises(ValueError, match="Неизвестный голос silero/nope"):
        await h.manager.download("silero", "nope")
    [ready] = h.kinds("voice_ready")
    assert ready["voice"] == "nope" and ready["ok"] is False and "Неизвестный" in str(ready["error"])
    await h.manager.aclose()


async def test_catalog_marks_current(tmp_path: Path) -> None:
    put_irina(tmp_path)
    h = Harness(tmp_path, no_download)
    await h.manager.open("piper", IRINA, retry=False)
    rows = h.manager.catalog()
    current = [r for r in rows if r["current"]]
    assert current == [
        {
            "kind": "piper",
            "voice": IRINA,
            "title": "Piper: Ирина",
            "size_mb": 63,
            "downloaded": True,
            "current": True,
        }
    ]
    assert len(rows) == 7
    await h.manager.aclose()


async def test_preview_returns_wav_and_caches_one_voice(tmp_path: Path) -> None:
    put_irina(tmp_path)
    put_silero(tmp_path)
    h = Harness(tmp_path, no_download)
    await h.manager.open("piper", IRINA, retry=False)

    data = await h.manager.preview("piper", IRINA, "normal", "Привет.")
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert w.getnframes() > 0
    assert h.built == [("piper", IRINA)]  # текущий голос не пересобирается

    await h.manager.preview("silero", "xenia", "normal", "Раз.")
    await h.manager.preview("silero", "xenia", "quiet", "Два.")
    assert h.built == [("piper", IRINA), ("silero", "xenia")]
    await h.manager.preview("silero", "baya", "normal", "Три.")
    await h.manager.preview("silero", "xenia", "normal", "Четыре.")
    assert h.built.count(("silero", "xenia")) == 2  # в кеше только последний

    with pytest.raises(VoiceNotDownloadedError):
        await h.manager.preview("vosk", "female_0", "normal", "Привет.")
    await h.manager.aclose()


async def test_aclose_leaves_no_tasks(tmp_path: Path) -> None:
    def broken(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        raise VoiceDownloadError("нет сети")

    h = Harness(tmp_path, broken, retry_delays_s=(60,))
    opening = asyncio.create_task(h.manager.open("silero", "xenia", retry=True))
    await asyncio.sleep(0.05)
    assert h.manager.state()["state"] == "downloading"
    await h.manager.aclose()
    assert await opening is False
    assert asyncio.all_tasks() == {asyncio.current_task()}
