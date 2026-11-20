"""Настройки коннектора из его smartesp.json: объявление, показ, правка через API."""

import json
from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, ConfigFile, ConnectorConfig
from smartesp.config.manifest import MASK, declared_settings, manifest_note, protected_key, settings_view


def project(tmp_path: Path, settings: object) -> Path:
    folder = tmp_path / "conn"
    folder.mkdir(exist_ok=True)
    (folder / "smartesp.json").write_text(json.dumps({"settings": settings}), encoding="utf-8")
    return folder


def connector(folder: Path, env: dict[str, str] | None = None) -> ConnectorConfig:
    args = ["run", "--project", str(folder), "my-mcp"]
    return ConnectorConfig(id="my", name="Моё", command="uv", args=args, env=env or {})


def store_with(tmp_path: Path, folder: Path, env: dict[str, str] | None = None) -> ConfigFile:
    entry = {"id": "my", "name": "Моё", "command": "uv", "args": ["run", "--project", str(folder), "my-mcp"]}
    if env:
        entry["env"] = env
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 4\n" + yaml.safe_dump({"connectors": [entry]}, allow_unicode=True), encoding="utf-8"
    )
    store = ConfigFile(path)
    store.load()
    return store


def env_of(store: ConfigFile, cid: str = "my") -> dict[str, str]:
    return next(c.env for c in store.config.connectors if c.id == cid)


CITY = {"key": "CITY", "title": "Город", "type": "text", "hint": "например, Москва"}
TOKEN = {"key": "API_TOKEN", "title": "Ключ", "type": "secret"}
FOLDERS = {"key": "FOLDERS", "title": "Папки", "type": "list"}
ROOT = {"key": "ROOT", "title": "Корень", "type": "path"}
FLAG = {"key": "ON", "title": "Включить", "type": "flag"}


# ---- объявление ----


def test_manifest_read_from_project_folder(tmp_path: Path) -> None:
    folder = project(tmp_path, [CITY, TOKEN])
    declared = declared_settings(connector(folder))
    assert [(s.key, s.title, s.type, s.hint) for s in declared] == [
        ("CITY", "Город", "text", "например, Москва"),
        ("API_TOKEN", "Ключ", "secret", ""),
    ]


def test_repo_placeholder_resolves_to_our_connectors() -> None:
    weather = ConnectorConfig(
        id="weather",
        name="Погода",
        command="uv",
        args=["run", "--project", "{repo}/connectors/weather", "weather-mcp"],
    )
    assert "WEATHER_PLACE" in [s.key for s in declared_settings(weather)]


@pytest.mark.parametrize(
    "content", ["", "{", '{"settings": 5}', '{"settings": [{"key": "1BAD", "title": "x"}]}']
)
def test_bad_or_missing_manifest_declares_nothing(tmp_path: Path, content: str) -> None:
    folder = tmp_path / "conn"
    folder.mkdir()
    if content:
        (folder / "smartesp.json").write_text(content, encoding="utf-8")
    assert declared_settings(connector(folder)) == []


def test_connector_without_project_declares_nothing() -> None:
    assert declared_settings(ConnectorConfig(id="x", name="X", command="/bin/x")) == []


@pytest.mark.parametrize(
    "key", ["PATH", "HOME", "SHELL", "PYTHONPATH", "PYTHONSTARTUP", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD"]
)
def test_protected_keys_never_declared(tmp_path: Path, key: str) -> None:
    assert protected_key(key)
    folder = project(tmp_path, [{"key": key, "title": "Зло", "type": "text"}, CITY])
    assert [s.key for s in declared_settings(connector(folder))] == ["CITY"]


@pytest.mark.parametrize("key", ["UV_INDEX_URL", "SMARTESP_CONNECTOR_DATA", "BASH_ENV", "ENV", "path"])
def test_more_protected_keys(key: str) -> None:
    assert protected_key(key)


def test_view_has_values_and_masks_secrets(tmp_path: Path) -> None:
    folder = project(tmp_path, [CITY, TOKEN, ROOT])
    view = settings_view(connector(folder, {"CITY": "Тверь", "API_TOKEN": "s3cret"}))
    assert view == [
        {"key": "CITY", "title": "Город", "type": "text", "hint": "например, Москва", "value": "Тверь"},
        {"key": "API_TOKEN", "title": "Ключ", "type": "secret", "hint": "", "value": MASK},
        {"key": "ROOT", "title": "Корень", "type": "path", "hint": "", "value": ""},
    ]


def test_secret_looking_key_is_masked_even_as_text(tmp_path: Path) -> None:
    folder = project(tmp_path, [{"key": "MY_API_KEY", "title": "Ключ", "type": "text"}])
    assert settings_view(connector(folder, {"MY_API_KEY": "k"}))[0]["value"] == MASK


def test_empty_secret_is_not_masked(tmp_path: Path) -> None:
    folder = project(tmp_path, [TOKEN])
    assert settings_view(connector(folder))[0]["value"] == ""


def test_store_lists_settings_by_connector(tmp_path: Path) -> None:
    store = store_with(tmp_path, project(tmp_path, [CITY]), {"CITY": "Тверь"})
    settings = store.connector_settings()
    assert settings["my"] == {
        "settings": settings_view(connector(tmp_path / "conn", {"CITY": "Тверь"})),
        "note": "",
        "example": "",
    }
    assert settings["my"]["settings"][0]["value"] == "Тверь"
    assert [s["key"] for s in settings["weather"]["settings"]][0] == "WEATHER_PLACE"


# ---- правка через API ----


def test_declared_key_is_saved_and_kept(tmp_path: Path) -> None:
    store = store_with(tmp_path, project(tmp_path, [CITY]))
    store.save(store.merge({"connectors": [{"id": "my", "env": {"CITY": "Москва"}}]}))
    assert env_of(store) == {"CITY": "Москва"}
    store.save(store.merge({"connectors": [{"id": "my", "enabled": False}]}))
    assert env_of(store) == {"CITY": "Москва"}


def test_enabled_and_env_together(tmp_path: Path) -> None:
    store = store_with(tmp_path, project(tmp_path, [CITY]))
    config = store.merge({"connectors": [{"id": "my", "enabled": False, "env": {"CITY": "Тверь"}}]})
    mine = next(c for c in config.connectors if c.id == "my")
    assert (mine.enabled, mine.env) == (False, {"CITY": "Тверь"})


def test_null_resets_declared_key(tmp_path: Path) -> None:
    store = store_with(tmp_path, project(tmp_path, [CITY]), {"CITY": "Тверь"})
    store.save(store.merge({"connectors": [{"id": "my", "env": {"CITY": None}}]}))
    assert env_of(store) == {}


def test_weather_place_via_api(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 4\n", encoding="utf-8")
    store = ConfigFile(path)
    store.load()
    store.save(store.merge({"connectors": [{"id": "weather", "env": {"WEATHER_PLACE": "Москва"}}]}))
    assert env_of(store, "weather")["WEATHER_PLACE"] == "Москва"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["connectors"] == [
        {"id": "weather", "env": {"WEATHER_PLACE": "Москва"}}
    ]


@pytest.mark.parametrize(
    "env",
    [
        {"OTHER": "x"},  # не объявлен
        {"PATH": "/tmp"},
        {"CITY": 5},
        {"CITY": "a" * 501},
        {"CITY": "a\nb"},
        {"CITY": "a\rb"},
        {"CITY": "a\x00b"},
        ["CITY"],
    ],
)
def test_bad_env_rejected(tmp_path: Path, env: object) -> None:
    store = store_with(tmp_path, project(tmp_path, [CITY]))
    with pytest.raises(ValueError):
        store.merge({"connectors": [{"id": "my", "env": env}]})


def test_malicious_manifest_cannot_unlock_path(tmp_path: Path) -> None:
    folder = project(tmp_path, [{"key": "PATH", "title": "x"}, {"key": "DYLD_LIBRARY_PATH", "title": "y"}])
    store = store_with(tmp_path, folder)
    for key in ("PATH", "DYLD_LIBRARY_PATH"):
        with pytest.raises(ValueError, match="config.yaml"):
            store.merge({"connectors": [{"id": "my", "env": {key: "/tmp"}}]})


def test_unchanged_secret_mask_keeps_value(tmp_path: Path) -> None:
    store = store_with(tmp_path, project(tmp_path, [TOKEN, CITY]), {"API_TOKEN": "s3cret"})
    store.save(store.merge({"connectors": [{"id": "my", "env": {"API_TOKEN": MASK, "CITY": "Тверь"}}]}))
    assert env_of(store) == {"API_TOKEN": "s3cret", "CITY": "Тверь"}
    store.save(store.merge({"connectors": [{"id": "my", "env": {"API_TOKEN": "new"}}]}))
    assert env_of(store)["API_TOKEN"] == "new"


@pytest.mark.parametrize("value", ["", "/Users/me/x", "~", "~/notes"])
def test_path_ok(tmp_path: Path, value: str) -> None:
    store = store_with(tmp_path, project(tmp_path, [ROOT]))
    store.merge({"connectors": [{"id": "my", "env": {"ROOT": value}}]})


@pytest.mark.parametrize("value", ["relative/dir", "{repo}/x", "~other/x"])
def test_path_must_be_absolute(tmp_path: Path, value: str) -> None:
    store = store_with(tmp_path, project(tmp_path, [ROOT]))
    with pytest.raises(ValueError, match="ROOT"):
        store.merge({"connectors": [{"id": "my", "env": {"ROOT": value}}]})


def test_folder_list_ok(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    store = store_with(tmp_path, project(tmp_path, [FOLDERS]))
    value = f"песочница={tmp_path / 'a'}; работа = {tmp_path / 'b'};"
    store.merge({"connectors": [{"id": "my", "env": {"FOLDERS": value}}]})
    store.merge({"connectors": [{"id": "my", "env": {"FOLDERS": ""}}]})


@pytest.mark.parametrize(
    "value",
    [
        "{tmp}/a",  # без имени
        "a=",  # без пути
        "=x",
        "a=relative",
        "a={tmp}/missing",  # папки нет
        "a={tmp}/file.txt",  # не папка
        "a={tmp}/a;A={tmp}/a",  # имя повторяется
    ],
)
def test_folder_list_rejected(tmp_path: Path, value: str) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    store = store_with(tmp_path, project(tmp_path, [FOLDERS]))
    with pytest.raises(ValueError, match="FOLDERS"):
        store.merge({"connectors": [{"id": "my", "env": {"FOLDERS": value.format(tmp=tmp_path)}}]})


@pytest.mark.parametrize(("value", "ok"), [("1", True), ("", True), ("0", False), ("yes", False)])
def test_flag_values(tmp_path: Path, value: str, ok: bool) -> None:
    store = store_with(tmp_path, project(tmp_path, [FLAG]))
    patch = {"connectors": [{"id": "my", "env": {"ON": value}}]}
    if ok:
        store.merge(patch)
    else:
        with pytest.raises(ValueError, match="ON"):
            store.merge(patch)


# ---- claude_tasks: ничего через API (решение W3-3) ----


def test_claude_tasks_declares_nothing_settable_but_explains() -> None:
    tasks = next(c for c in Config().connectors if c.id == "claude_tasks")
    assert declared_settings(tasks) == []
    assert "config.yaml" in manifest_note(tasks)["note"]
    assert "CLAUDE_TASK_FOLDERS" in manifest_note(tasks)["example"]


@pytest.mark.parametrize(
    "env", [{"CLAUDE_TASK_FOLDERS": "home=~"}, {"CLAUDE_TASK_TOOLS": "Bash"}, {"CLAUDE_TASK_ENV": "X"}]
)
def test_claude_tasks_env_rejected(tmp_path: Path, env: dict[str, str]) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 4\n", encoding="utf-8")
    store = ConfigFile(path)
    store.load()
    with pytest.raises(ValueError, match="меняют только в config.yaml"):
        store.merge({"connectors": [{"id": "claude_tasks", "env": env}]})


def test_note_read_from_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "conn"
    folder.mkdir()
    (folder / "smartesp.json").write_text(
        '{"note": "Только руками", "example": "env: {A: b}"}', encoding="utf-8"
    )
    assert manifest_note(connector(folder)) == {"note": "Только руками", "example": "env: {A: b}"}
    assert manifest_note(ConnectorConfig(id="x", name="X", command="/bin/x")) == {"note": "", "example": ""}
