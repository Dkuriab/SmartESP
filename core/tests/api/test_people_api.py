"""API людей: реестр, запись образцов с колонки, узнавания, модель отпечатков."""

from pathlib import Path

import httpx
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from fakes.fake_playback import FakeFilePlayback
from fakes.fake_voiceprint import FakeVoicePrint, voice_pcm
from smartesp.api import LogBuffer, create_api
from smartesp.contracts import Utterance
from smartesp.events import EventBus
from smartesp.people import People

from .conftest import HEADERS, PORT, TOKEN

P = "/api/v1/people"


def _people(tmp_path: Path, heard: list[bytes | None], ready: bool = True) -> People:
    model = tmp_path / "m.onnx"
    if ready:
        model.write_bytes(b"onnx")

    async def record(device_id: str) -> bytes | None:
        return heard.pop(0)

    return People(
        tmp_path / "people", model, FakeVoicePrint(), lambda progress: None, record, lambda d: d == "A"
    )


def _client(people: People | None) -> httpx.AsyncClient:
    app = FastAPI()
    api = create_api(
        FakeCore(), EventBus(), TOKEN, port=PORT, files=FakeFilePlayback(), logs=LogBuffer(), people=people
    )
    app.include_router(api)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_add_record_rename_delete(tmp_path: Path) -> None:
    people = _people(tmp_path, [voice_pcm(1), None])
    async with _client(people) as client:
        anya = (await client.post(P, json={"name": "Аня"}, headers=HEADERS)).json()
        assert anya["name"] == "Аня" and anya["samples"] == [] and anya["stale_samples"] == 0
        url = f"{P}/{anya['id']}"
        sample = (await client.post(f"{url}/samples", json={"device_id": "A"}, headers=HEADERS)).json()
        assert (sample["seconds"], sample["peak_db"], sample["device_id"]) == (2.0, -6.0, "A")
        assert "embedding" not in sample
        silent = await client.post(f"{url}/samples", json={"device_id": "A"}, headers=HEADERS)
        assert silent.status_code == 422
        busy = await client.post(f"{url}/samples", json={"device_id": "B"}, headers=HEADERS)
        assert busy.status_code == 409
        renamed = (await client.patch(url, json={"name": "Анна"}, headers=HEADERS)).json()
        assert renamed["name"] == "Анна" and len(renamed["samples"]) == 1
        listed = (await client.get(P, headers=HEADERS)).json()
        assert [p["name"] for p in listed] == ["Анна"]
        gone = await client.delete(f"{url}/samples/{sample['id']}", headers=HEADERS)
        assert gone.status_code == 204
        assert (await client.delete(url, headers=HEADERS)).status_code == 204
        assert (await client.delete(url, headers=HEADERS)).status_code == 404
        assert (await client.get(P)).status_code == 401  # без токена


async def test_links(tmp_path: Path) -> None:
    async with _client(_people(tmp_path, [])) as client:
        anya = (await client.post(P, json={"name": "Аня"}, headers=HEADERS)).json()
        bob = (await client.post(P, json={"name": "Боб"}, headers=HEADERS)).json()
        assert anya["links"] == []
        link = {"channel": "telegram", "account": "111"}
        linked = (await client.post(f"{P}/{anya['id']}/links", json=link, headers=HEADERS)).json()
        assert linked["links"] == [link]
        taken = await client.post(f"{P}/{bob['id']}/links", json=link, headers=HEADERS)
        assert taken.status_code == 422 and "Аня" in taken.json()["detail"]
        bad = await client.post(
            f"{P}/{bob['id']}/links", json={"channel": "Tg", "account": "1"}, headers=HEADERS
        )
        assert bad.status_code == 422
        gone = await client.delete(f"{P}/{anya['id']}/links/telegram/111", headers=HEADERS)
        assert gone.status_code == 200 and gone.json()["links"] == []
        again = await client.delete(f"{P}/{anya['id']}/links/telegram/111", headers=HEADERS)
        assert again.status_code == 404


async def test_bad_names(tmp_path: Path) -> None:
    async with _client(_people(tmp_path, [])) as client:
        await client.post(P, json={"name": "Аня"}, headers=HEADERS)
        assert (await client.post(P, json={"name": "аня"}, headers=HEADERS)).status_code == 422
        assert (await client.post(P, json={"name": "a/b"}, headers=HEADERS)).status_code == 422
        assert (await client.patch(f"{P}/00000000", json={"name": "X"}, headers=HEADERS)).status_code == 404


async def test_recognitions_and_model(tmp_path: Path) -> None:
    people = _people(tmp_path, [voice_pcm(1)])
    async with _client(people) as client:
        anya = (await client.post(P, json={"name": "Аня"}, headers=HEADERS)).json()
        await client.post(f"{P}/{anya['id']}/samples", json={"device_id": "A"}, headers=HEADERS)
        await people.recognize(Utterance("A", 9, voice_pcm(1), 0.0))
        (seen,) = (await client.get(f"{P}/recognitions", headers=HEADERS)).json()
        assert (seen["name"], seen["person_id"], seen["turn"], seen["score"]) == ("Аня", anya["id"], 9, 1.0)
        model = (await client.get(f"{P}/model", headers=HEADERS)).json()
        assert model["ready"] and not model["downloading"] and model["size_mb"] == 28
        started = await client.post(f"{P}/model", headers=HEADERS)
        assert started.status_code == 202 and started.json()["ready"]


async def test_model_missing_blocks_recording(tmp_path: Path) -> None:
    people = _people(tmp_path, [voice_pcm(1)], ready=False)
    async with _client(people) as client:
        anya = (await client.post(P, json={"name": "Аня"}, headers=HEADERS)).json()
        refused = await client.post(f"{P}/{anya['id']}/samples", json={"device_id": "A"}, headers=HEADERS)
        assert refused.status_code == 409 and "модель" in refused.json()["detail"]


async def test_without_people_module() -> None:
    async with _client(None) as client:
        assert (await client.get(P, headers=HEADERS)).json() == []
        assert (await client.get(f"{P}/model", headers=HEADERS)).status_code == 404
