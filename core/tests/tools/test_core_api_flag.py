"""Флаг core_api в smartesp.json: коннектор получает адрес и токен API ядра, остальные — нет."""

import json
from pathlib import Path

from smartesp.config import Config, ConnectorConfig, wants_core_api
from smartesp.tools import ConnectorSpec, McpHub
from smartesp.tools.connector import Connector

CORE_ENV = {"SMARTESP_URL": "http://127.0.0.1:9", "SMARTESP_TOKEN": "t"}


def project(tmp_path: Path, manifest: object) -> ConnectorConfig:
    folder = tmp_path / "conn"
    folder.mkdir()
    (folder / "smartesp.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ConnectorConfig(
        id="music", name="Музыка", command="uv", args=["run", "--project", str(folder), "x"]
    )


def test_flag_read_from_manifest(tmp_path: Path) -> None:
    assert wants_core_api(project(tmp_path, {"settings": [], "core_api": True}))
    assert not wants_core_api(ConnectorConfig(id="x", name="X", command="/bin/x"))


def test_flag_false_by_default(tmp_path: Path) -> None:
    assert not wants_core_api(project(tmp_path, {"settings": []}))


async def test_only_flagged_connector_gets_core_env(tmp_path: Path) -> None:
    hub = McpHub(tmp_path, client_env=CORE_ENV)
    flagged = hub._make(ConnectorSpec("a", "A", "/bin/true", core_api=True))  # pyright: ignore[reportPrivateUsage]
    plain = hub._make(ConnectorSpec("b", "B", "/bin/true"))  # pyright: ignore[reportPrivateUsage]
    assert isinstance(flagged, Connector) and isinstance(plain, Connector)
    flagged_env = flagged._env()  # pyright: ignore[reportPrivateUsage]
    plain_env = plain._env()  # pyright: ignore[reportPrivateUsage]
    assert flagged_env["SMARTESP_TOKEN"] == "t" and flagged_env["SMARTESP_URL"] == CORE_ENV["SMARTESP_URL"]
    assert plain_env.get("SMARTESP_TOKEN") != "t"


def test_our_music_connector_asks_for_core_api() -> None:
    connectors = {c.id: c for c in Config().connectors}
    assert wants_core_api(connectors["music"]) and not wants_core_api(connectors["weather"])
