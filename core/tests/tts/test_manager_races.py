"""Тесты гонок менеджера голосов: одна попытка при присоединении повторов, брошенные скачивания."""

import asyncio
import threading
from pathlib import Path

from manager_harness import Harness, Progress, put_silero

from fakes.fake_events import RecordingSink
from smartesp.tts import VoiceDownloadError
from smartesp.tts._fetcher import SharedFetcher, _Shared  # pyright: ignore[reportPrivateUsage]


async def test_single_attempt_starter_is_not_held_by_retry_joiner(tmp_path: Path) -> None:
    gate = threading.Event()
    calls: list[int] = []

    def failing(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        calls.append(1)
        gate.wait(2)
        raise VoiceDownloadError("нет сети")

    h = Harness(tmp_path, failing, retry_delays_s=(0.05,))
    first = asyncio.create_task(h.manager.open("silero", "xenia", retry=False))
    while not calls:
        await asyncio.sleep(0.01)
    second = asyncio.create_task(h.manager.open("silero", "xenia", retry=True))
    await asyncio.sleep(0.01)
    gate.set()
    async with asyncio.timeout(1):
        assert await first is False  # итог одной попытки, а не всех повторов
    assert not second.done()  # повторы идут дальше
    await h.manager.aclose()
    assert await second is False


async def test_new_fetch_after_abandoned_finished_thread_does_not_download_again(tmp_path: Path) -> None:
    gate = threading.Event()
    started = threading.Event()
    calls: list[str] = []

    def stubborn(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        # не зовёт progress, поэтому не обрывается и докачивает после ухода ждущего
        calls.append(voice)
        started.set()
        gate.wait(2)
        put_silero(home)

    h = Harness(tmp_path, stubborn)
    first = asyncio.create_task(h.manager.download("silero", "xenia"))
    assert await asyncio.to_thread(started.wait, 2)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    second = asyncio.create_task(h.manager.download("silero", "xenia"))
    await asyncio.sleep(0.05)
    gate.set()
    async with asyncio.timeout(2):
        await second
    assert calls == ["xenia"]
    await h.manager.aclose()


async def test_finished_shared_fetch_is_not_reused(tmp_path: Path) -> None:
    calls: list[str] = []

    def download(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        calls.append(voice)
        put_silero(home)

    fetcher = SharedFetcher(tmp_path, download, RecordingSink().publish)
    stale = asyncio.create_task(asyncio.sleep(0))
    await stale
    target = tmp_path / "voices" / "silero" / "v5_ru.pt"
    fetcher._fetches[target] = _Shared(stale)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    await fetcher.fetch("silero", "xenia")
    assert calls == ["xenia"]  # законченное скачивание не засчитано за новое
    await fetcher.aclose()
