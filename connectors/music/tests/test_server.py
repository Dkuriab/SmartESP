"""Инструменты через клиентскую сессию SDK в памяти; API ядра и станции — MockTransport."""

import json
from pathlib import Path
from typing import Any

import httpx
from mcp import Client
from mcp.types import TextContent

from music_mcp.server import build_server

CORE = {"SMARTESP_URL": "http://core:8765", "SMARTESP_TOKEN": "t"}
KITCHEN = {"device_id": "aa:01", "name": "Кухня", "available": True, "state": "idle", "title": "", "index": 0,
           "count": 0, "position_s": 0.0, "live": False, "volume": 0.6, "error": ""}  # fmt: skip
HALL = {**KITCHEN, "device_id": "aa:02", "name": "Зал"}


class FakeCore:
    """Ядро: запоминает запросы; play/control отвечают «играет»; refuse — отказ с текстом."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.refuse = ""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "radio.example":
            return httpx.Response(200, text="[playlist]\nFile1=https://stream.example/live.mp3\n")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        assert request.headers["Authorization"] == "Bearer t"
        if self.refuse:
            return httpx.Response(409, json={"detail": self.refuse})
        if request.method == "GET":
            return httpx.Response(200, json=[KITCHEN, HALL])
        items = (body or {}).get("items") or [{"title": "Песня"}]
        volume = (body or {}).get("volume") or 0.7
        state = {
            **KITCHEN,
            "state": "playing",
            "title": items[0]["title"],
            "count": len(items),
            "volume": volume,
        }
        return httpx.Response(200, json=state)


async def call(
    core: FakeCore, name: str, args: dict[str, object] | None = None, env: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[bool, str]:  # fmt: skip
    server = build_server({**CORE, **(env or {})}, httpx.MockTransport(core))
    async with Client(server) as client:
        result = await client.call_tool(name, args or {}, meta=meta)  # type: ignore[arg-type]
    text = "".join(part.text for part in result.content if isinstance(part, TextContent))
    return bool(result.is_error), text


def music_env(tmp_path: Path) -> dict[str, str]:
    for name in ("a.mp3", "b.mp3"):
        (tmp_path / name).write_bytes(b"x")
    return {"MUSIC_FOLDERS": f"Музыка={tmp_path}"}


async def test_play_files_on_speaker_of_the_call(tmp_path: Path) -> None:
    core = FakeCore()
    error, text = await call(core, "speaker_music_play", {}, music_env(tmp_path), meta={"device": "aa:09"})
    assert not error and text == "На колонке «Кухня» играет «a» (1 из 2)."
    method, path, body = core.requests[-1]
    assert (method, path, body["device_id"]) == ("POST", "/api/v1/streams", "aa:09")
    assert [i["source"] for i in body["items"]] == [str(tmp_path / "a.mp3"), str(tmp_path / "b.mp3")]


async def test_named_speaker_wins_and_unknown_is_explained(tmp_path: Path) -> None:
    core = FakeCore()
    await call(core, "speaker_music_play", {"speaker": "зале"}, music_env(tmp_path), meta={"device": "aa:01"})
    assert core.requests[-1][2]["device_id"] == "aa:02"
    error, text = await call(core, "speaker_music_play", {"speaker": "спальня"}, music_env(tmp_path))
    assert error and "Нет колонки «спальня»" in text and "«Кухня», «Зал»" in text


async def test_radio_resolves_playlist(tmp_path: Path) -> None:
    core = FakeCore()
    env = {"MUSIC_RADIO": "Джаз=https://radio.example/jazz.pls"}
    error, text = await call(core, "speaker_radio_play", {"station": "джаз"}, env)
    assert not error and "Радио «Джаз»" in text
    assert core.requests[-1][2]["items"] == [
        {"source": "https://stream.example/live.mp3", "title": "Радио «Джаз»"}
    ]


async def test_mac_audio_uses_device_setting() -> None:
    core = FakeCore()
    await call(core, "speaker_mac_audio_play", {"speaker": "кухня"}, {"MUSIC_MAC_DEVICE": "Loopback"})
    assert core.requests[-1][2]["items"] == [{"source": "capture:Loopback", "title": "Звук Mac"}]
    await call(core, "speaker_mac_audio_play")
    assert core.requests[-1][2] == {
        "device_id": None,
        "items": [{"source": "capture:BlackHole", "title": "Звук Mac"}],
    }


async def test_controls_and_volume() -> None:
    core = FakeCore()
    for action in ("pause", "resume", "next", "previous", "stop"):
        error, _ = await call(core, f"speaker_music_{action}")
        assert not error and core.requests[-1] == (
            "POST",
            "/api/v1/streams/control",
            {"device_id": None, "action": action},
        )
    error, text = await call(core, "speaker_music_volume", {"percent": 30})
    assert core.requests[-1][2] == {"device_id": None, "volume": 0.3, "delta": 0.0}
    assert not error and text.startswith("Громкость музыки на колонке «Кухня»")
    await call(core, "speaker_music_volume", {})
    assert core.requests[-1][2]["delta"] == 0.1
    await call(core, "speaker_music_volume", {"delta": -20, "speaker": "кухня"})
    assert core.requests[-1][2] == {"device_id": "aa:01", "volume": None, "delta": -0.2}


async def test_core_refusal_and_missing_api(tmp_path: Path) -> None:
    core = FakeCore()
    core.refuse = "Колонка не в сети"
    error, text = await call(core, "speaker_music_pause")
    assert error and text.endswith("Колонка не в сети")  # приставку SDK снимает ядро
    server = build_server({}, httpx.MockTransport(core))
    async with Client(server) as client:
        result = await client.call_tool("speaker_music_stop", {})
    assert result.is_error


async def test_status_and_library(tmp_path: Path) -> None:
    core = FakeCore()
    error, text = await call(core, "speaker_music_status")
    assert not error and text == "На колонке «Кухня» ничего не играет. На колонке «Зал» ничего не играет."
    error, text = await call(core, "speaker_music_library", env=music_env(tmp_path))
    assert not error and "Музыка (2 файлов)" in text and "Радиостанции не заданы" in text
