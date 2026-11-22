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


async def test_steps_job_and_runs(tmp_path: Path) -> None:
    import asyncio
    import sys

    async with _client(tmp_path, None) as client:
        manifest = json.loads((tmp_path / "trainers" / "ww" / "smartesp.json").read_text("utf-8"))
        manifest["command"] = [sys.executable, "-c"]
        manifest["steps"] = [
            {"id": "train", "title": "Обучить", "per_target": True, "args": ["print('{target}')"]}
        ]
        (tmp_path / "trainers" / "ww" / "smartesp.json").write_text(json.dumps(manifest), "utf-8")
        assert (await client.get(f"{P}/ww/job", headers=HEADERS)).json() is None
        started = await client.post(f"{P}/ww/steps/train", json={"target": "kuzya"}, headers=HEADERS)
        assert started.status_code == 202 and started.json()["status"] == "running"
        job = started.json()
        for _ in range(100):
            job = (await client.get(f"{P}/ww/job", headers=HEADERS)).json()
            if job["status"] != "running":
                break
            await asyncio.sleep(0.05)
        assert job["status"] == "done" and job["log"] == ["kuzya"]
        assert (await client.post(f"{P}/ww/steps/nope", json={}, headers=HEADERS)).status_code == 404
        assert (await client.get(f"{P}/ww/runs", headers=HEADERS)).json() == []
        assert (await client.delete(f"{P}/ww/job", headers=HEADERS)).status_code == 204


async def test_firmware_upload_and_device_file_route(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from smartesp.api import add_device_files
    from smartesp.updates import Updates

    sent: list[dict[str, object]] = []

    async def send(device_id: str, payload: dict[str, object]) -> bool:
        sent.append(payload)
        return device_id == "A"

    updates = Updates(tmp_path / "u", send)
    app = FastAPI()
    app.include_router(
        create_api(
            FakeCore(),
            EventBus(),
            TOKEN,
            port=PORT,
            files=FakeFilePlayback(),
            logs=LogBuffer(),
            updates=updates,
        )
    )
    add_device_files(app, updates)
    firmware = bytes([0xE9]) + b"\x01" * 99
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        files = {"firmware": ("fw.bin", firmware, "application/octet-stream")}
        ok = await client.post("/api/v1/devices/A/firmware", files=files, headers=HEADERS)
        assert ok.status_code == 202
        link = str(sent[0]["path"])
        got = await client.get(link)  # колонка — без токена API
        assert got.status_code == 200 and got.content == firmware
        assert (await client.get("/device/files/подделка")).status_code == 404
        old = await client.post("/api/v1/devices/B/firmware", files=files, headers=HEADERS)
        assert old.status_code == 409 and "0.5.0" in old.json()["detail"]
        junk = await client.post(
            "/api/v1/devices/A/firmware", files={"firmware": ("x", b"PK", "x")}, headers=HEADERS
        )
        assert junk.status_code == 409
