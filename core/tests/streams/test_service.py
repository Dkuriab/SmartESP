"""Потоки на колонках: очередь, переходы по отчётам колонки, пауза с позицией, выбор колонки."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from fakes.fake_events import RecordingSink
from fakes.fake_streams import FakeStreamLink
from smartesp.contracts import DeviceInfo, StreamCommand, StreamItem, StreamRefused, StreamReport
from smartesp.streams import Streams

SECOND = 32000


def info(device_id: str, *, connected: bool = True) -> DeviceInfo:
    return DeviceInfo(device_id, f"Колонка {device_id}", connected, "10.0.0.5:1", "0.6.0", 1.0, 5)


class Env:
    """Потоки с подделками: две колонки, d1 умеет потоки; last — колонка последнего разговора."""

    def __init__(self, tmp: Path, start_timeout_s: float = 5.0, stop_wait_s: float = 0.2) -> None:
        self.link = FakeStreamLink(("d1",))
        self.devices = [info("d1"), info("d2")]
        self.last: str | None = "d1"
        self.events = RecordingSink()
        self.decoded: list[tuple[str, float]] = []
        self.rates: list[int] = []
        self.probe_error = ""
        self.files = [tmp / f"{n}.mp3" for n in ("one", "two", "three")]
        for file in self.files:
            file.write_bytes(b"ID3")
        self.streams = Streams(
            self.link,
            lambda: self.devices,
            lambda: self.last,
            self._decode,
            events=self.events,
            probe=self._probe,
            start_timeout_s=start_timeout_s,
            stop_wait_s=stop_wait_s,
        )

    async def _decode(self, source: str, start_s: float, rate: int) -> AsyncGenerator[bytes]:
        self.decoded.append((source, start_s))
        self.rates.append(rate)
        if source.endswith("broken.mp3"):
            raise ValueError("не разобрать")
        yield b"\x01\x00" * 4
        yield b"\x02\x00" * 4

    async def _probe(self, source: str) -> str:
        return self.probe_error if source.startswith("capture:") else ""

    def items(self, count: int = 3) -> list[StreamItem]:
        return [StreamItem(str(f), f.stem) for f in self.files[:count]]

    def report(self, state: str, played: int = 0, error: str = "", stream: int | None = None) -> None:
        command = self.start()
        number = command.stream if stream is None else stream
        self.streams.report("d1", StreamReport(number, state, played, error))  # type: ignore[arg-type]

    def start(self) -> StreamCommand:
        return next(c for _, c in reversed(self.link.sent) if c.kind == "start")

    def token(self) -> str:
        return self.start().path.removeprefix("/device/stream/")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path, start_timeout_s=5.0, stop_wait_s=0.2)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_play_sends_start_with_link_and_volume(env: Env) -> None:
    result = await env.streams.play(None, env.items(), volume=0.4)
    command = env.start()
    assert (command.kind, command.rate, command.volume, command.live) == ("start", 16000, 0.4, False)
    assert command.path.startswith("/device/stream/")
    assert (result.state, result.title, result.index, result.count) == ("playing", "one", 0, 3)
    assert env.events.events[-1][0] == "stream"


async def test_link_opens_once_and_decodes_from_start(env: Env) -> None:
    await env.streams.play("d1", env.items(), start_s=12.5)
    token = env.token()
    audio = await env.streams.open(token)
    assert audio is not None
    assert b"".join([chunk async for chunk in audio]) == b"\x01\x00" * 4 + b"\x02\x00" * 4
    assert env.decoded == [(str(env.files[0]), 12.5)]
    assert await env.streams.open(token) is None
    assert await env.streams.open("nope") is None


async def test_broken_source_gives_no_audio(env: Env, tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"x")
    await env.streams.play("d1", [StreamItem(str(broken))])
    assert await env.streams.open(env.token()) is None


async def test_ended_goes_to_next_and_last_ends_queue(env: Env) -> None:
    await env.streams.play("d1", env.items(2))
    first = env.start().stream
    env.report("ended", SECOND * 3)
    await settle()
    assert env.start().stream != first
    assert env.streams.status()[0].index == 1
    env.report("ended", SECOND)
    await settle()
    state = env.streams.status()[0]
    assert (state.state, state.error) == ("idle", "")


async def test_failed_skips_and_three_in_a_row_stop(env: Env) -> None:
    await env.streams.play("d1", env.items(3) + env.items(3))
    for _ in range(2):
        env.report("failed", error="download")
        await settle()
    assert env.streams.status()[0].index == 2
    env.report("failed", error="download")
    await settle()
    state = env.streams.status()[0]
    assert (state.state, state.error) == ("idle", "Не получилось открыть «three»")
    assert env.link.last().kind == "stop"


async def test_rate_failure_stops_with_hint(env: Env) -> None:
    await env.streams.play("d1", env.items())
    env.report("failed", error="rate")
    await settle()
    assert "частоту" in env.streams.status()[0].error


async def test_pause_takes_position_from_stopped_and_resume_seeks(env: Env) -> None:
    await env.streams.play("d1", env.items(), start_s=10.0)
    stream = env.start().stream

    async def speaker_stops() -> None:
        await asyncio.sleep(0.01)
        env.streams.report("d1", StreamReport(stream, "stopped", SECOND * 5))

    stopper = asyncio.create_task(speaker_stops())
    paused = await env.streams.control(None, "pause")
    await stopper
    assert env.link.last() == StreamCommand("stop", stream)
    assert (paused.state, paused.position_s) == ("paused", 15.0)
    resumed = await env.streams.control(None, "resume")
    assert resumed.state == "playing"
    assert await env.streams.open(env.token()) is not None
    assert env.decoded[-1] == (str(env.files[0]), 15.0)


async def test_live_source_resumes_from_now(env: Env) -> None:
    await env.streams.play("d1", [StreamItem("https://radio.example/live.mp3", "Радио")])
    assert env.start().live
    env.report("playing", SECOND * 60)
    paused = await env.streams.control("d1", "pause")  # колонка не ответила stopped — ждём недолго
    assert (paused.state, paused.position_s, paused.live) == ("paused", 0.0, True)


async def test_next_previous_stop_and_volume(env: Env) -> None:
    await env.streams.play("d1", env.items())
    assert (await env.streams.control(None, "next")).index == 1
    assert (await env.streams.control(None, "previous")).index == 0
    assert (await env.streams.control(None, "previous")).index == 0
    volume = await env.streams.set_volume(None, delta=0.3)
    assert volume.volume == 0.9 and env.link.last() == StreamCommand("volume", volume=0.9)
    assert (await env.streams.set_volume(None, delta=0.5)).volume == 1.0
    assert (await env.streams.control(None, "stop")).state == "idle"
    with pytest.raises(StreamRefused) as refused:
        await env.streams.control(None, "pause")
    assert refused.value.reason == "not_playing"
    await env.streams.play("d1", env.items())
    assert env.start().volume == 1.0  # громкость колонки запомнена


async def test_next_on_last_item_stops(env: Env) -> None:
    await env.streams.play("d1", env.items(1))
    assert (await env.streams.control(None, "next")).state == "idle"


async def test_disconnect_pauses_and_stale_reports_are_ignored(env: Env) -> None:
    await env.streams.play("d1", env.items(), start_s=3.0)
    env.report("playing", SECOND * 2)
    env.report("ended", stream=999)  # чужой поток
    await settle()
    assert env.streams.status()[0].index == 0
    env.streams.report("d1", None)
    state = next(s for s in env.streams.status() if s.device_id == "d1")
    assert (state.state, state.position_s, state.error) == ("paused", 5.0, "Колонка отключилась")


async def test_watchdog_stops_silent_speaker(tmp_path: Path) -> None:
    env = Env(tmp_path, start_timeout_s=0.02, stop_wait_s=0.1)
    await env.streams.play("d1", env.items())
    await asyncio.sleep(0.08)
    state = env.streams.status()[0]
    assert (state.state, state.error) == ("idle", "Колонка не начала играть")


async def test_refusals(env: Env) -> None:
    cases: list[tuple[str | None, list[StreamItem], str]] = [
        ("zz", env.items(), "unknown_device"),
        ("d2", env.items(), "unsupported"),
        ("d1", [], "bad_source"),
        ("d1", [StreamItem("relative.mp3")], "bad_source"),
        ("d1", [StreamItem("/etc/passwd")], "bad_source"),
    ]
    for device, items, reason in cases:
        with pytest.raises(StreamRefused) as refused:
            await env.streams.play(device, items)
        assert refused.value.reason == reason
    env.devices = [info("d1", connected=False), info("d2")]
    with pytest.raises(StreamRefused) as refused:
        await env.streams.play("d1", env.items())
    assert refused.value.reason == "offline"


async def test_capture_probe_refuses_with_hint(env: Env) -> None:
    env.probe_error = "Нет устройства ввода «BlackHole»"
    with pytest.raises(StreamRefused) as refused:
        await env.streams.play("d1", [StreamItem("capture:BlackHole")])
    assert (refused.value.reason, str(refused.value)) == ("bad_source", env.probe_error)
    env.probe_error = ""
    state = await env.streams.play("d1", [StreamItem("capture:BlackHole")])
    assert (state.title, state.live, env.start().live) == ("Звук Mac", True, True)
    env.report("failed", error="download")
    await settle()
    assert "доступ к микрофону" in env.streams.status()[0].error


async def test_device_choice(env: Env) -> None:
    env.last = None
    await env.streams.play(None, env.items())  # единственная умеющая
    env.link.supported.add("d2")
    env.last = "d2"
    assert (await env.streams.play(None, env.items())).device_id == "d2"  # колонка разговора
    env.last = None
    with pytest.raises(StreamRefused) as refused:
        await env.streams.control(None, "pause")
    assert refused.value.reason == "no_device"
    env.last = "d2"
    assert (await env.streams.control(None, "stop")).device_id == "d2"
    assert (await env.streams.control(None, "stop")).device_id == "d1"  # осталась одна с потоком


async def test_offline_on_send_pauses(env: Env) -> None:
    env.link.online = False
    with pytest.raises(StreamRefused) as refused:
        await env.streams.play("d1", env.items(), start_s=4.0)
    assert refused.value.reason == "offline"
    state = env.streams.status()[0]
    assert (state.state, state.position_s) == ("paused", 4.0)


async def test_status_lists_capable_and_closing_stops(env: Env) -> None:
    assert [s.device_id for s in env.streams.status()] == ["d1"]
    await env.streams.play("d1", env.items())
    stream = env.start().stream
    await env.streams.aclose()
    assert env.link.last() == StreamCommand("stop", stream)
    with pytest.raises(StreamRefused):
        await env.streams.play("d1", env.items())


async def test_hifi_speaker_gets_48k_and_position_counts_its_bytes(env: Env) -> None:
    env.link.rates["d1"] = 48000
    await env.streams.play("d1", env.items(), start_s=2.0)
    assert env.start().rate == 48000
    assert await env.streams.open(env.token()) is not None
    assert env.rates[-1] == 48000
    env.report("playing", 96000 * 3)  # 3 с при 48 кГц
    assert env.streams.status()[0].position_s == 5.0
