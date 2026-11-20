"""Коннекторы владельца сливаются с умолчаниями по id: в файле — только отличия."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, ConfigFile, load_config
from smartesp.config import connectors as defaults_module
from smartesp.config.connectors import DEFAULT_CONNECTORS

DEFAULT_IDS = [cid for cid, *_ in DEFAULT_CONNECTORS]


def by_id(config: Config) -> dict[str, dict[str, object]]:
    return {c.id: c.model_dump() for c in config.connectors}


def stored(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("connectors")


def store_with(tmp_path: Path, text: str = "") -> ConfigFile:
    path = tmp_path / "config.yaml"
    path.write_text("version: 4\n" + text, encoding="utf-8")
    store = ConfigFile(path)
    store.load()
    return store


def test_owner_fields_override_one_default_env_merges_by_key() -> None:
    config = Config.model_validate({"connectors": [{"id": "weather", "env": {"WEATHER_PLACE": "Москва"}}]})
    assert [c.id for c in config.connectors] == DEFAULT_IDS
    weather = by_id(config)["weather"]
    default = by_id(Config())["weather"]
    assert weather == {**default, "env": {"WEATHER_PLACE": "Москва"}}
    assert by_id(config)["calc"] == by_id(Config())["calc"]


def test_enabled_false_switches_off_and_remove_hides() -> None:
    config = Config.model_validate(
        {"connectors": [{"id": "calc", "enabled": False}, {"id": "food", "remove": True}]}
    )
    assert "food" not in by_id(config)
    assert by_id(config)["calc"]["enabled"] is False
    assert "remove" not in by_id(config)["calc"]  # служебный ключ в настройки не попадает


def test_env_null_removes_a_default_key() -> None:
    config = Config.model_validate({"connectors": [{"id": "weather", "env": {"WEATHER_PLACE": None}}]})
    assert by_id(config)["weather"]["env"] == {}


def test_new_default_reaches_owner_with_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = store_with(tmp_path, "connectors:\n  - {id: calc, enabled: false}\n")
    newer = (*DEFAULT_CONNECTORS, ("radio", "Радио", {}, True))
    monkeypatch.setattr(defaults_module, "DEFAULT_CONNECTORS", newer)
    config = store.load()
    assert [c.id for c in config.connectors] == [*DEFAULT_IDS, "radio"]
    assert by_id(config)["calc"]["enabled"] is False


def test_toggle_patch_saves_only_id_and_enabled(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    store.save(store.merge({"connectors": [{"id": "calc", "enabled": False}]}))
    assert stored(tmp_path / "config.yaml") == [{"id": "calc", "enabled": False}]
    assert [c.id for c in store.config.connectors] == DEFAULT_IDS


def test_patches_merge_with_earlier_owner_entries(tmp_path: Path) -> None:
    store = store_with(tmp_path, "connectors:\n  - {id: weather, env: {WEATHER_PLACE: Москва}}\n")
    store.save(store.merge({"connectors": [{"id": "weather", "enabled": False}]}))
    assert stored(tmp_path / "config.yaml") == [
        {"id": "weather", "enabled": False, "env": {"WEATHER_PLACE": "Москва"}}
    ]
    store.save(store.merge({"connectors": [{"id": "weather", "enabled": True}]}))
    assert stored(tmp_path / "config.yaml") == [{"id": "weather", "env": {"WEATHER_PLACE": "Москва"}}]


@pytest.mark.parametrize(
    "entries",
    [
        [{"id": "calc", "command": "/bin/sh", "args": ["-c", "echo"]}],
        [{"id": "calc", "args": ["-c", "echo"]}],
        [{"id": "weather", "env": {"WEATHER_PLACE": "Москва"}}],
        [{"id": "calc", "name": "Счёт"}],
        [{"id": "food", "remove": True}],
        [{"id": "my", "name": "Моё", "command": "/bin/my"}],
        [{"id": "my", "enabled": True}],  # новый id — даже без команды
        [c.model_dump() for c in Config().connectors],  # полный список с командами
        ["calc"],
        None,  # сброс списка стёр бы окружение и коннекторы владельца
    ],
)
def test_api_patch_may_only_toggle_known_connectors(tmp_path: Path, entries: object) -> None:
    store = store_with(tmp_path, "connectors:\n  - {id: weather, env: {WEATHER_PLACE: Тверь}}\n")
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="меняют только в config.yaml"):
        store.merge({"connectors": entries})
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before


def test_api_patch_toggles_owner_added_connector(tmp_path: Path) -> None:
    mine = "connectors:\n  - {id: my, name: Моё, command: /bin/my}\n"
    store = store_with(tmp_path, mine)
    store.save(store.merge({"connectors": [{"id": "my", "enabled": False}]}))
    assert by_id(store.config)["my"]["enabled"] is False
    assert by_id(store.config)["my"]["command"] == "/bin/my"


def test_legacy_full_list_keeps_working_and_shrinks_on_save(tmp_path: Path) -> None:
    legacy = [c.model_dump() for c in Config().connectors if c.id in DEFAULT_IDS[:5]]  # до mac_media
    legacy[3]["env"] = {"WEATHER_PLACE": "Тверь"}
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 4\n" + yaml.safe_dump({"connectors": legacy}, allow_unicode=True), encoding="utf-8"
    )
    store = ConfigFile(path)
    config = store.load()
    assert [c.id for c in config.connectors] == DEFAULT_IDS  # mac_media и claude_tasks пришли сами
    assert by_id(config)["weather"]["env"] == {"WEATHER_PLACE": "Тверь"}
    store.save(store.merge({"connectors": [{"id": "calc", "enabled": False}]}))
    assert stored(path) == [
        {"id": "calc", "enabled": False},
        {"id": "weather", "env": {"WEATHER_PLACE": "Тверь"}},
    ]


def test_new_id_without_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="command"):
        Config.model_validate({"connectors": [{"id": "ghost", "enabled": False}]})


def test_load_config_reads_small_form(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 4\nconnectors:\n  - id: claude_tasks\n    enabled: true\n"
        "    env: {CLAUDE_TASK_FOLDERS: 'sandbox=/tmp/s'}\n",
        encoding="utf-8",
    )
    tasks = by_id(load_config(path))["claude_tasks"]
    assert tasks["enabled"] is True and tasks["env"] == {"CLAUDE_TASK_FOLDERS": "sandbox=/tmp/s"}
    assert tasks["command"] == "uv"
