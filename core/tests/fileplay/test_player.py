"""Тесты проигрывания файла на колонке: подделки колонок, разбора и событий."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

import pytest

from fakes.fake_device_port import FakeDevicePort
from fakes.fake_events import RecordingSink
from smartesp.contracts import AskUnavailable, AudioUndecodable, Delivery, DeviceInfo, PlaybackRefused
from smartesp.fileplay import FilePlayer

FILE = b"ID3-fake-mp3"


def info(device_id: str, *, connected: bool = True, protocol: int = 3) -> DeviceInfo:
    return DeviceInfo(device_id, device_id, connected, "10.0.0.5:1", "1.0", 1.0, protocol)


class HeldPort(FakeDevicePort):
    """Колонка, которая держит звук: после каждого куска ждёт gate; before — итог без звука."""

    def __init__(self) -> None:
        super().__init__()
        self.proactive = {"d1", "d2"}
        self.gate = asyncio.Event()
        self.gate.set()
        self.pulled = asyncio.Event()
        self.received: list[bytes] = []
        self.before: Delivery | None = None
        self.result: Delivery = "delivered"
        self.hold = asyncio.Event()  # до первого куска колонка ждёт его (ход не начат)
        self.hold.set()

    async def announce(self, device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        try:
            if self.before is not None:
                return self.before
            await self.hold.wait()
            async for chunk in audio:
                self.received.append(chunk)
                self.pulled.set()
                await self.gate.wait()
            return self.result
        finally:
            if isinstance(audio, AsyncGenerator):
                await audio.aclose()


class Decoder:
    """Подделка разбора: отдаёт содержимое файла кусками PCM или бросает ошибку."""

    def __init__(self) -> None:
        self.seen: list[bytes] = []
        self.paths: list[Path] = []
        self.error: Exception | None = None
        self.closed = 0
        self.close_s = 0.0  # сколько «останавливается ffmpeg» при закрытии

    async def __call__(self, path: Path) -> AsyncGenerator[bytes]:
        self.paths.append(path)
        self.seen.append(path.read_bytes())
        try:
            if self.error is not None:
                raise self.error
            yield b"pcm1"
            yield b"pcm2"
        finally:
            if self.close_s:
                await asyncio.sleep(self.close_s)
            self.closed += 1


async def upload(data: bytes = FILE) -> AsyncIterator[bytes]:
    for start in range(0, len(data), 4):
        yield data[start : start + 4]


@pytest.fixture
def port() -> HeldPort:
    return HeldPort()


@pytest.fixture
def decoder() -> Decoder:
    return Decoder()


@pytest.fixture
def events() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def devices() -> list[DeviceInfo]:
    return [info("d1"), info("d2"), info("off", connected=False), info("v2", protocol=2)]


@pytest.fixture
def player(
    port: HeldPort, decoder: Decoder, events: RecordingSink, devices: list[DeviceInfo], tmp_path: Path
) -> FilePlayer:
    return FilePlayer(port, lambda: devices, decoder, events=events, tmp_dir=tmp_path)


async def finished(events: RecordingSink, count: int = 1) -> None:
    async with asyncio.timeout(2):
        while sum(kind == "playback_finished" for kind, _ in events.events) < count:
            await asyncio.sleep(0.01)


async def test_plays_decoded_file_and_reports(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    await player.play_file("d1", upload())
    await finished(events)
    assert decoder.seen == [FILE]
    assert port.received == [b"pcm1", b"pcm2"]
    assert events.events == [
        ("playback_started", {"device_id": "d1"}),
        ("playback_finished", {"device_id": "d1", "delivery": "delivered"}),
    ]
    assert list(tmp_path.iterdir()) == []  # временный файл убран
    assert decoder.closed == 1


@pytest.mark.parametrize(
    ("device_id", "reason"),
    [("nope", "unknown_device"), ("off", "offline"), ("v2", "unsupported")],
)
async def test_refuses_devices(
    player: FilePlayer, port: HeldPort, decoder: Decoder, device_id: str, reason: str
) -> None:
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file(device_id, upload())
    assert refused.value.reason == reason
    assert decoder.seen == [] and port.received == []


async def test_v2_message_is_clear(player: FilePlayer) -> None:
    with pytest.raises(PlaybackRefused, match="прошивк"):
        await player.play_file("v2", upload())


async def test_one_file_per_speaker(player: FilePlayer, port: HeldPort, events: RecordingSink) -> None:
    port.gate.clear()
    await player.play_file("d1", upload())
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("d1", upload())
    assert refused.value.reason == "busy"
    await player.play_file("d2", upload())  # другая колонка свободна
    port.gate.set()
    await finished(events, 2)
    await player.play_file("d1", upload())  # доиграл — снова можно


async def test_concurrent_requests_reserve_speaker(player: FilePlayer, decoder: Decoder) -> None:
    async def slow() -> AsyncIterator[bytes]:
        await asyncio.sleep(0.05)
        yield FILE

    first = asyncio.create_task(player.play_file("d1", slow()))
    await asyncio.sleep(0)
    with pytest.raises(PlaybackRefused, match="уже играет"):
        await player.play_file("d1", upload())
    await first
    assert len(decoder.seen) == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [(AudioUndecodable("не разобрать"), "undecodable"), (AskUnavailable("нет ffmpeg"), "unavailable")],
)
async def test_decode_errors_refuse(
    player: FilePlayer,
    port: HeldPort,
    decoder: Decoder,
    events: RecordingSink,
    tmp_path: Path,
    error: Exception,
    reason: str,
) -> None:
    decoder.error = error
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("d1", upload())
    assert refused.value.reason == reason
    assert str(refused.value) == str(error)
    assert port.received == [] and events.events == []
    assert list(tmp_path.iterdir()) == []
    decoder.error = None
    await player.play_file("d1", upload())  # колонка снова свободна


@pytest.mark.parametrize(("delivery", "reason"), [("busy", "busy"), ("lost", "offline")])
async def test_speaker_refusal_before_sound(
    player: FilePlayer,
    port: HeldPort,
    decoder: Decoder,
    events: RecordingSink,
    tmp_path: Path,
    delivery: Delivery,
    reason: str,
) -> None:
    port.before = delivery
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("d1", upload())
    assert refused.value.reason == reason
    assert events.events == []  # не начинался — событий нет
    assert list(tmp_path.iterdir()) == []
    assert decoder.closed == 1


async def test_interrupted_by_wake_is_reported(
    player: FilePlayer, port: HeldPort, events: RecordingSink
) -> None:
    port.result = "interrupted"
    await player.play_file("d1", upload())
    await finished(events)
    assert events.events[-1] == ("playback_finished", {"device_id": "d1", "delivery": "interrupted"})


async def test_stop_cancels_playback(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    port.gate.clear()
    await player.play_file("d1", upload())
    assert await player.stop_file("d1") is True
    assert events.events[-1] == ("playback_finished", {"device_id": "d1", "delivery": "interrupted"})
    assert list(tmp_path.iterdir()) == []
    assert decoder.closed == 1
    assert await player.stop_file("d1") is False  # уже не играет
    with pytest.raises(PlaybackRefused) as refused:
        await player.stop_file("nope")
    assert refused.value.reason == "unknown_device"


async def test_aclose_stops_all_and_refuses_new(
    player: FilePlayer, port: HeldPort, events: RecordingSink, tmp_path: Path
) -> None:
    port.gate.clear()
    await player.play_file("d1", upload())
    await player.play_file("d2", upload())
    await player.aclose()
    assert [data["delivery"] for kind, data in events.events if kind == "playback_finished"] == [
        "interrupted",
        "interrupted",
    ]
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("d1", upload())
    assert refused.value.reason == "unavailable"


async def slow_upload() -> AsyncIterator[bytes]:
    await asyncio.sleep(0.05)
    yield FILE


async def test_stop_while_uploading_refuses_start(
    player: FilePlayer, port: HeldPort, events: RecordingSink, tmp_path: Path
) -> None:
    playing = asyncio.create_task(player.play_file("d1", slow_upload()))
    await asyncio.sleep(0.01)
    assert await player.stop_file("d1") is True
    with pytest.raises(PlaybackRefused) as refused:
        await playing
    assert refused.value.reason == "stopped"
    assert port.received == [] and events.events == []
    assert list(tmp_path.iterdir()) == []
    await player.play_file("d1", upload())  # колонка свободна


async def test_close_while_uploading_is_unavailable(
    player: FilePlayer, port: HeldPort, tmp_path: Path
) -> None:
    playing = asyncio.create_task(player.play_file("d1", slow_upload()))
    await asyncio.sleep(0.01)
    await player.aclose()
    with pytest.raises(PlaybackRefused) as refused:
        await playing
    assert refused.value.reason == "unavailable"
    assert port.received == [] and list(tmp_path.iterdir()) == []


async def test_stop_before_first_chunk_is_stopped(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    port.hold.clear()
    playing = asyncio.create_task(player.play_file("d1", upload()))
    await asyncio.sleep(0.01)
    assert await player.stop_file("d1") is True
    with pytest.raises(PlaybackRefused) as refused:
        await playing
    assert refused.value.reason == "stopped"
    assert events.events == [] and list(tmp_path.iterdir()) == []
    assert decoder.closed == 1


async def test_cancel_before_task_starts_cleans_up(
    player: FilePlayer, decoder: Decoder, tmp_path: Path
) -> None:
    loop = asyncio.get_running_loop()
    original = decoder.__call__

    async def decode(path: Path) -> AsyncGenerator[bytes]:
        # отмена задачи хода раньше её первого шага: колбэк встаёт в очередь раньше задачи
        loop.call_soon(lambda: player._tasks["d1"].cancel())  # pyright: ignore[reportPrivateUsage]
        async for chunk in original(path):
            yield chunk

    player._decode = decode  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(PlaybackRefused) as refused:
        await player.play_file("d1", upload())
    assert refused.value.reason == "stopped"
    await asyncio.sleep(0.01)
    assert list(tmp_path.iterdir()) == []
    assert decoder.closed == 1
    player._decode = decoder  # pyright: ignore[reportPrivateUsage]
    await player.play_file("d1", upload())  # колонка не осталась занятой


async def test_wall_clock_cap(
    port: HeldPort, decoder: Decoder, events: RecordingSink, devices: list[DeviceInfo], tmp_path: Path
) -> None:
    player = FilePlayer(port, lambda: devices, decoder, events=events, tmp_dir=tmp_path, max_s=0.05)
    port.gate.clear()
    await player.play_file("d1", upload())
    await finished(events)
    assert events.events[-1] == ("playback_finished", {"device_id": "d1", "delivery": "interrupted"})
    assert list(tmp_path.iterdir()) == []


def finished_count(events: RecordingSink) -> int:
    return sum(kind == "playback_finished" for kind, _ in events.events)


async def stopped_cleanly(
    player: FilePlayer, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    """Ровно один итог, временного файла нет, разбор закрыт, колонка снова свободна."""
    await asyncio.sleep(decoder.close_s * 2)
    assert finished_count(events) == 1
    assert events.events[-1] == ("playback_finished", {"device_id": "d1", "delivery": "interrupted"})
    assert list(tmp_path.iterdir()) == []
    assert decoder.closed == 1
    await player.play_file("d1", upload())


@pytest.mark.parametrize("second", ["stop", "preempt", "aclose"])
async def test_concurrent_stops_are_safe(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path, second: str
) -> None:
    port.gate.clear()
    decoder.close_s = 0.05
    await player.play_file("d1", upload())
    first = asyncio.create_task(player.stop_file("d1"))
    await asyncio.sleep(0.01)  # первая остановка уже закрывает разбор
    if second == "aclose":
        await asyncio.gather(first, player.aclose())
        await asyncio.sleep(decoder.close_s * 2)
        assert finished_count(events) == 1 and list(tmp_path.iterdir()) == [] and decoder.closed == 1
        return
    again = player.stop_file("d1") if second == "stop" else player.preempt("d1")
    assert await asyncio.gather(first, again) == [True, True]
    await stopped_cleanly(player, decoder, events, tmp_path)


async def test_simultaneous_stop_and_preempt(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    port.gate.clear()
    decoder.close_s = 0.05
    await player.play_file("d1", upload())
    assert await asyncio.gather(player.preempt("d1"), player.stop_file("d1"), player.stop_file("d1")) == [
        True,
        True,
        True,
    ]
    await stopped_cleanly(player, decoder, events, tmp_path)


async def test_cancelled_stop_caller_does_not_recancel(
    player: FilePlayer, port: HeldPort, decoder: Decoder, events: RecordingSink, tmp_path: Path
) -> None:
    port.gate.clear()
    decoder.close_s = 0.05
    await player.play_file("d1", upload())
    stopping = asyncio.create_task(player.stop_file("d1"))
    await asyncio.sleep(0.01)
    stopping.cancel()  # запрос DELETE оборвался посреди остановки
    await asyncio.sleep(0)
    await stopped_cleanly(player, decoder, events, tmp_path)


async def test_preempt_leaves_upload_alone(player: FilePlayer, port: HeldPort) -> None:
    playing = asyncio.create_task(player.play_file("d1", slow_upload()))
    await asyncio.sleep(0.01)
    assert await player.preempt("d1") is False  # колонку занимает не файл
    await playing
    assert port.received


async def test_preempted_before_first_chunk_says_so(player: FilePlayer, port: HeldPort) -> None:
    port.hold.clear()
    playing = asyncio.create_task(player.play_file("d1", upload()))
    await asyncio.sleep(0.01)
    assert await player.preempt("d1") is True
    with pytest.raises(PlaybackRefused, match="объявлением") as refused:
        await playing
    assert refused.value.reason == "stopped"
