"""Ход через API в собранном ядре на подделках: /ask и /ask/voice, лента ходов, неготовность."""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import pytest
from core_harness import HEADERS, client, eventually, fake_kinds, make_core, ollama_factory

from fakes.fake_executor import FakeOllama
from smartesp.stt import find_ffmpeg
from smartesp.wiring import finish, start, stop


def silence_wav(seconds: float = 0.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(bytes(int(32000 * seconds)))
    return buffer.getvalue()


async def test_ask_text_goes_through_core_and_feed(tmp_path: Path) -> None:
    made: list[FakeOllama] = []
    core = make_core(tmp_path, fake_kinds(ollama_factory(made)))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    body = {"text": "Который час?", "person": "Аня", "source": "telegram"}
    async with client(core) as http:
        response = await http.post("/api/v1/ask", json=body, headers=HEADERS)
        turns = (await http.get("/api/v1/turns", headers=HEADERS)).json()
    assert response.status_code == 200
    assert response.json() == {"answer": "Сейчас полдень.", "turn_id": "api1"}
    turn = turns[0]
    assert (turn["turn_id"], turn["origin"], turn["source"], turn["person"]) == (
        "api1",
        "api",
        "telegram",
        "Аня",
    )
    assert turn["device_name"] == "Telegram"
    assert core.history.messages()[-1].content == "Сейчас полдень."
    await stop(core)
    await finish(core)


@pytest.mark.skipif(find_ffmpeg() is None, reason="нет ffmpeg")
async def test_ask_voice_decodes_and_recognizes(tmp_path: Path) -> None:
    core = make_core(tmp_path, fake_kinds(ollama_factory([]), text="Который час?"))
    start(core)
    await eventually(lambda: core.core.state == "ready")
    files = {"audio": ("voice.wav", silence_wav(), "audio/wav")}
    async with client(core) as http:
        response = await http.post(
            "/api/v1/ask/voice", files=files, data={"person": "Аня", "source": "telegram"}, headers=HEADERS
        )
        garbage = await http.post(
            "/api/v1/ask/voice", files={"audio": ("voice.ogg", b"junk" * 50, "audio/ogg")}, headers=HEADERS
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Сейчас полдень."
    assert core.history.messages()[0].content == "[Telegram · Аня] Который час?"
    assert garbage.status_code == 422
    assert "OGG/Opus" in garbage.json()["detail"]
    await stop(core)
    await finish(core)


async def test_ask_while_warming_is_503(tmp_path: Path) -> None:
    gate = asyncio.Event()
    core = make_core(tmp_path, fake_kinds(ollama_factory([], warm_gate=gate)))
    start(core)
    async with client(core) as http:
        response = await http.post("/api/v1/ask", json={"text": "Привет"}, headers=HEADERS)
    assert response.status_code == 503
    gate.set()
    await stop(core)
    await finish(core)
