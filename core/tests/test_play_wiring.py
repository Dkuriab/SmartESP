"""Файл на колонке в собранном ядре: HTTP → ffmpeg → ход ядра на поддельной колонке → остановка."""

from __future__ import annotations

import io
import wave
from contextlib import aclosing
from pathlib import Path

import pytest
from core_harness import (
    HEADERS,
    client,
    connect,
    eventually,
    fake_kinds,
    make_core,
    ollama_factory,
    sent_types,
)

from smartesp.stt import find_ffmpeg
from smartesp.wiring import finish, start, stop

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="нет ffmpeg")


def silence_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(bytes(int(32000 * seconds)))
    return buffer.getvalue()


async def test_play_and_stop_file(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([])))
    start(core)
    conn, _ = await connect(core, "A", protocol=3)
    old, _ = await connect(core, "B", protocol=2)
    files = {"audio": ("long.wav", silence_wav(30.0), "audio/wav")}
    async with aclosing(core.bus.subscribe()) as events, client(core) as http:
        response = await http.post("/api/v1/devices/A/play", files=files, headers=HEADERS)
        assert response.status_code == 202
        assert sent_types(conn)[:2] == ["announce", "reply_start"]
        await eventually(lambda: len(conn.sent_audio()) > 0)
        busy = await http.post("/api/v1/devices/A/play", files=files, headers=HEADERS)
        assert (busy.status_code, busy.json()) == (409, {"detail": "На колонке уже играет файл"})
        v2 = await http.post("/api/v1/devices/B/play", files=files, headers=HEADERS)
        assert v2.status_code == 409 and "прошивк" in v2.json()["detail"]
        junk = {"audio": ("junk.mp3", b"not audio at all", "audio/mpeg")}
        assert (await http.post("/api/v1/devices/A/play", files=junk, headers=HEADERS)).status_code == 409
        stopped = await http.delete("/api/v1/devices/A/play", headers=HEADERS)
        assert stopped.json() == {"stopped": True}
        assert "cancel_turn" in sent_types(conn)
        undecodable = await http.post("/api/v1/devices/A/play", files=junk, headers=HEADERS)
        assert undecodable.status_code == 422
        unknown = await http.post("/api/v1/devices/nope/play", files=files, headers=HEADERS)
        assert unknown.status_code == 404
        kinds = []
        async for event in events:
            if event.kind.startswith("playback_"):
                kinds.append((event.kind, event.data))
            if event.kind == "playback_finished":
                break
    assert kinds == [
        ("playback_started", {"device_id": "A"}),
        ("playback_finished", {"device_id": "A", "delivery": "interrupted"}),
    ]
    assert "announce" not in sent_types(old)
    await stop(core)
    await finish(core)
