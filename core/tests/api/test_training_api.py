"""API обучения: наборы, цели, запись с колонки, файлы записей."""

import json
from pathlib import Path

import httpx
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from smartesp.api import LogBuffer, create_api
from smartesp.events import EventBus
from smartesp.training import Training

from .conftest import HEADERS, PORT, TOKEN

P = "/api/v1/training"


def _client(tmp_path: Path, pcm: bytes | None) -> httpx.AsyncClient:
    folder = tmp_path / "trainers" / "ww"
    folder.mkdir(parents=True)
    targets = [{"id": "kuzya", "title": "Кузя", "positive": ["Кузя"], "negative": ["Вася"]}]
    (folder / "smartesp.json").write_text(
        json.dumps({"id": "ww", "title": "Слово", "targets": targets}), "utf-8"
    )

    async def record(device_id: str) -> bytes | None:
        return pcm

    training = Training(tmp_path / "trainers", tmp_path / "data", record, lambda d: d == "A")
    app = FastAPI()
    app.include_router(
        create_api(
            FakeCore(),
            EventBus(),
            TOKEN,
            port=PORT,
            files=FakeFilePlayback(),
            logs=LogBuffer(),
            training=training,
        )
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_kits_record_listen_and_delete(tmp_path: Path) -> None:
    async with _client(tmp_path, b"\x00\x40" * 16000) as client:
        kits = (await client.get(P, headers=HEADERS)).json()
        assert kits[0]["targets"][0] == {
            "id": "kuzya",
            "title": "Кузя",
            "positive": ["Кузя"],
            "negative": ["Вася"],
        }
        body = {"device_id": "A", "phrase": "Кузя", "person": "Данила"}
        saved = (await client.post(f"{P}/ww/record", json=body, headers=HEADERS)).json()
        assert saved == {"name": "0001.wav", "seconds": 1.0, "peak_db": -6.0}
        who = {"phrase": "Кузя", "person": "Данила"}
        assert [
            r["name"] for r in (await client.get(f"{P}/ww/recordings", params=who, headers=HEADERS)).json()
        ] == ["0001.wav"]
        wav = await client.get(f"{P}/ww/recordings/0001.wav", params=who, headers=HEADERS)
        assert (
            wav.status_code == 200
            and wav.headers["content-type"] == "audio/wav"
            and wav.content[:4] == b"RIFF"
        )
        assert (
            await client.delete(f"{P}/ww/recordings/0001.wav", params=who, headers=HEADERS)
        ).status_code == 204
        assert (
            await client.get(f"{P}/ww/recordings/0001.wav", params=who, headers=HEADERS)
        ).status_code == 404
        assert (await client.get(P)).status_code == 401  # без токена


async def test_record_errors_and_targets(tmp_path: Path) -> None:
    async with _client(tmp_path, None) as client:
        body = {"device_id": "A", "phrase": "Кузя", "person": "Данила"}
        assert (await client.post(f"{P}/ww/record", json=body, headers=HEADERS)).status_code == 422  # тишина
        busy = {**body, "device_id": "B"}
        assert (await client.post(f"{P}/ww/record", json=busy, headers=HEADERS)).status_code == 409
        unknown = {**body, "phrase": "Петя"}
        assert (await client.post(f"{P}/ww/record", json=unknown, headers=HEADERS)).status_code == 404
        targets = [{"id": "kuzya", "title": "Кузя", "positive": ["Кузя", "Кузьма"], "negative": []}]
        kit = (await client.put(f"{P}/ww/targets", json=targets, headers=HEADERS)).json()
        assert [p["phrase"] for p in kit["phrases"]] == ["Кузя", "Кузьма"]
        bad = [{"id": "kuzya", "title": "", "positive": []}]
        assert (await client.put(f"{P}/ww/targets", json=bad, headers=HEADERS)).status_code == 422
        assert (await client.put(f"{P}/nope/targets", json=targets, headers=HEADERS)).status_code == 404
