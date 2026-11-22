from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from fakes.fake_core import FakeCore, make_turn
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


async def test_connectors(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.get(f"{P}/connectors", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == core.connector_items
    assert (await client.get(f"{P}/connectors")).status_code == 401


async def test_status_voice_before_open_and_without_error(client: httpx.AsyncClient, core: FakeCore) -> None:
    # так отдаёт состояние настоящий VoiceManager: до open() вида нет, ошибки нет — None
    core.voice_state = {"kind": None, "voice": None, "state": "missing", "error": None}
    response = await client.get(f"{P}/status", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["voice"] == core.voice_state


async def test_config_and_patch(client: httpx.AsyncClient, core: FakeCore) -> None:
    config = (await client.get(f"{P}/config", headers=HEADERS)).json()
    assert config == core.config()
    assert config["executor_prompts"] == {"dispatcher": "Ты помощник.", "big": "Ты большая модель."}
    response = await client.patch(f"{P}/config", json={"tts": {"kind": "silero"}}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"change_id": 1, "status": "accepted", "error": ""}
    assert core.patches == [{"tts": {"kind": "silero"}}]


async def test_config_masks_secret_env_of_connectors(
    client: httpx.AsyncClient, core: FakeCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"API_KEY": "k1", "bot_token": "t1", "Password": "p", "MY_SECRET": "", "WEATHER_PLACE": "Тверь"}
    full = {**core.config(), "effective": {"connectors": [{"id": "w", "env": env}, {"id": "c"}]}}
    monkeypatch.setattr(core, "config", lambda: full)
    shown = (await client.get(f"{P}/config", headers=HEADERS)).json()["effective"]["connectors"]
    assert shown[0]["env"] == {
        "API_KEY": "•••",
        "bot_token": "•••",
        "Password": "•••",
        "MY_SECRET": "",  # пустое — не задано, скрывать нечего
        "WEATHER_PLACE": "Тверь",
    }
    assert shown[1] == {"id": "c"}
    assert env["API_KEY"] == "k1"  # настройки ядра не тронуты


async def test_config_masks_declared_secrets(
    client: httpx.AsyncClient, core: FakeCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WEATHER_PIN объявлен секретом (в FakeCore.connector_items), хотя по имени им не выглядит
    env = {"WEATHER_PLACE": "Тверь", "WEATHER_PIN": "1234"}
    full = {
        **core.config(),
        "effective": {"connectors": [{"id": "weather", "env": env}, {"id": "notes", "env": env}]},
    }
    monkeypatch.setattr(core, "config", lambda: full)
    shown = (await client.get(f"{P}/config", headers=HEADERS)).json()["effective"]["connectors"]
    assert shown[0]["env"] == {"WEATHER_PLACE": "Тверь", "WEATHER_PIN": "•••"}
    assert shown[1]["env"] == env  # у notes этот ключ секретом не объявлен


@pytest.mark.parametrize(("status", "code"), [("restart_required", 200), ("invalid", 422), ("stopping", 503)])
async def test_patch_status_codes(client: httpx.AsyncClient, core: FakeCore, status: str, code: int) -> None:
    core.patch_status = status
    response = await client.patch(f"{P}/config", json={"a": 1}, headers=HEADERS)
    assert response.status_code == code
    assert response.json()["status"] == status
    if status == "invalid":
        assert response.json()["error"] == "неверная правка"


async def test_models(client: httpx.AsyncClient, core: FakeCore) -> None:
    models = (await client.get(f"{P}/models", headers=HEADERS)).json()
    assert models == [{"name": "qwen", "size_bytes": 42, "supports_tools": True}]
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
    core.download_status = "invalid"
    response = await client.post(f"{P}/voices/download", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.json() == {"change_id": 7, "status": "invalid", "error": "Неизвестный голос"}


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
    assert response.json()[0]["at"] == 1700000000.5


async def test_turns_path_and_delegations(client: httpx.AsyncClient, core: FakeCore) -> None:
    delegation = {"from": "dispatcher", "to": "big", "task": "посчитай", "auto": False}
    core.turn_items = [
        {**make_turn(5), "path": ["dispatcher", "big"], "delegations": [delegation]},
        make_turn(4),
    ]
    turns = (await client.get(f"{P}/turns", headers=HEADERS)).json()
    assert turns[0]["path"] == ["dispatcher", "big"]
    assert turns[0]["delegations"] == [delegation]
    assert (turns[1]["path"], turns[1]["delegations"]) == ([], [])  # ходы до передачи задач


async def test_turns_tool_calls(client: httpx.AsyncClient, core: FakeCore) -> None:
    used = {"executor": "dispatcher", "connector": "calc", "tool": "calc_add", "ok": True}
    core.turn_items = [{**make_turn(5), "tools": [used]}, make_turn(4)]
    turns = (await client.get(f"{P}/turns", headers=HEADERS)).json()
    assert turns[0]["tools"] == [
        {**used, "arguments": {}, "result": ""}
    ]  # старые ходы — без запроса и ответа
    assert turns[1]["tools"] == []  # ходы до подсветки инструментов


async def test_turns_origin_kind_and_undelivered(client: httpx.AsyncClient, core: FakeCore) -> None:
    late = {"origin": "core", "kind": "announcement", "status": "undelivered", "path": ["big"]}
    core.turn_items = [
        {**make_turn(6), **late, "turn_id": "late5"},
        {**make_turn(5), "origin": "listen"},
        make_turn(4),
    ]
    turns = (await client.get(f"{P}/turns", headers=HEADERS)).json()
    assert [(t["turn_id"], t["origin"], t["kind"], t["status"]) for t in turns] == [
        ("late5", "core", "announcement", "undelivered"),
        (5, "listen", "turn", "ok"),
        (4, "wake", "turn", "ok"),  # ходы до речи по инициативе
    ]


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
    (tmp_path / "app-1a2b.js").write_text("1", encoding="utf-8")
    app: FastAPI = make_app(core, bus, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        root = await c.get("/")
        assert root.text == "<h1>UI</h1>"
        # страница — без кэша (окно приложения иначе показывает старую после обновления)
        assert root.headers["cache-control"] == "no-cache"
        assert "cache-control" not in (await c.get("/app-1a2b.js")).headers
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
    download = paths[f"{P}/voices/download"]["post"]["responses"]
    assert "ChangeOut" in str(download["503"]) and "ChangeOut" in str(download["422"])
    assert "ErrorOut" in str(paths[f"{P}/models"]["get"]["responses"]["502"])
    assert "401" in paths[f"{P}/status"]["get"]["responses"]


async def test_access_lists_lan_urls_without_loopback(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smartesp.api.routes.lan_addresses", lambda: ["10.0.0.5"])
    response = await client.get(f"{P}/access", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"urls": ["http://10.0.0.5:8765/?token=secret-token"]}


async def test_access_requires_token(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{P}/access")).status_code == 401


async def test_config_masks_cloud_key_and_lists_cloud_models(
    client: httpx.AsyncClient, core: FakeCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloud = {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "api_key": "sk-or-1"}
    full = {**core.config(), "effective": {"cloud": cloud}}
    monkeypatch.setattr(core, "config", lambda: full)
    shown = (await client.get(f"{P}/config", headers=HEADERS)).json()["effective"]["cloud"]
    assert shown == {**cloud, "api_key": "•••"} and cloud["api_key"] == "sk-or-1"
    models = (await client.get(f"{P}/cloud/models", headers=HEADERS)).json()
    assert models[0]["id"] == "google/gemini-2.5-flash" and models[0]["tools"] is True
