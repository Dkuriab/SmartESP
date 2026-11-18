from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore
from smartesp.contracts import ExecutorError, VoiceNotDownloadedError
from smartesp.events import EventBus

from .conftest import HEADERS, make_app

P = "/api/v1"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic secret-token"},
        {"Authorization": "secret-token"},
    ],
)
async def test_bad_auth_is_401_without_leak(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    for method, path in [("GET", "/status"), ("PATCH", "/config"), ("POST", "/restart"), ("GET", "/turns")]:
        response = await client.request(method, P + path, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}


async def test_status(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.get(f"{P}/status", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == await core.status()


async def test_config_and_patch(client: httpx.AsyncClient, core: FakeCore) -> None:
    assert (await client.get(f"{P}/config", headers=HEADERS)).json() == core.config()
    response = await client.patch(f"{P}/config", json={"tts": {"kind": "silero"}}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"change_id": 1, "status": "accepted", "error": ""}
    assert core.patches == [{"tts": {"kind": "silero"}}]


@pytest.mark.parametrize(("status", "code"), [("restart_required", 200), ("invalid", 422), ("stopping", 503)])
async def test_patch_status_codes(client: httpx.AsyncClient, core: FakeCore, status: str, code: int) -> None:
    core.patch_status = status
    response = await client.patch(f"{P}/config", json={"a": 1}, headers=HEADERS)
    assert response.status_code == code
    assert response.json()["status"] == status
    if status == "invalid":
        assert response.json()["error"] == "неверная правка"


async def test_models(client: httpx.AsyncClient, core: FakeCore) -> None:
    assert (await client.get(f"{P}/models", headers=HEADERS)).json() == [{"name": "qwen", "size_bytes": 42}]
    core.models_error = ExecutorError("ollama down")
    response = await client.get(f"{P}/models", headers=HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"] == "ollama down"


async def test_voices_and_download(client: httpx.AsyncClient, core: FakeCore) -> None:
    voices = (await client.get(f"{P}/voices", headers=HEADERS)).json()
    assert voices[0]["voice"] == "irina"
    body = {"kind": "piper", "voice": "irina"}
    response = await client.post(f"{P}/voices/download", json=body, headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {"change_id": 7, "status": "accepted", "error": ""}
    core.download_status = "stopping"
    response = await client.post(f"{P}/voices/download", json=body, headers=HEADERS)
    assert response.status_code == 503


async def test_preview(client: httpx.AsyncClient, core: FakeCore) -> None:
    body = {"kind": "piper", "voice": "irina"}
    response = await client.post(f"{P}/voices/preview", json=body, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFfake"
    assert core.previews == [("piper", "irina", "normal", "Привет! Я буду отвечать этим голосом.")]


@pytest.mark.parametrize(
    ("error", "code"),
    [(VoiceNotDownloadedError("x"), 409), (ValueError("x"), 404), (RuntimeError("тишина"), 500)],
)
async def test_preview_errors(client: httpx.AsyncClient, core: FakeCore, error: Exception, code: int) -> None:
    core.preview_error = error
    body = {"kind": "piper", "voice": "irina", "text": "эй"}
    response = await client.post(f"{P}/voices/preview", json=body, headers=HEADERS)
    assert response.status_code == code
    assert "detail" in response.json()


async def test_turns(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{P}/turns?limit=2", headers=HEADERS)
    assert [t["turn_id"] for t in response.json()] == [3, 2]
    assert response.json()[0]["first_audio_ms"] is None


async def test_restart(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.post(f"{P}/restart", headers=HEADERS)
    assert response.status_code == 202
    assert core.restarts == 1


async def test_root_without_build(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert "cd ui" in response.text
    assert "npm run build" in response.text


async def test_root_with_build(core: FakeCore, bus: EventBus, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>UI</h1>", encoding="utf-8")
    app: FastAPI = make_app(core, bus, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/")).text == "<h1>UI</h1>"
        assert (await c.get(f"{P}/status")).status_code == 401  # API побеждает статику
        assert (await c.get(f"{P}/status", headers=HEADERS)).status_code == 200


async def test_bearer_scheme_case_insensitive_but_strict_spacing(client: httpx.AsyncClient) -> None:
    ok = await client.get(f"{P}/status", headers={"Authorization": "bearer secret-token"})
    assert ok.status_code == 200
    bad = await client.get(f"{P}/status", headers={"Authorization": "Bearer  secret-token"})
    assert bad.status_code == 401


def test_openapi_declares_error_bodies(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    patch = paths[f"{P}/config"]["patch"]["responses"]
    assert {"401", "422", "503"} <= set(patch)
    assert "ChangeOut" in str(patch["422"]) and "ChangeOut" in str(patch["503"])
    assert "ChangeOut" in str(paths[f"{P}/voices/download"]["post"]["responses"]["503"])
    assert "ErrorOut" in str(paths[f"{P}/models"]["get"]["responses"]["502"])
    assert "401" in paths[f"{P}/status"]["get"]["responses"]
