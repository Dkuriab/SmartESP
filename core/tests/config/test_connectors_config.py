"""Тесты раздела connectors в настройках."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, ConfigFile, ConnectorConfig, load_config

REPO = Path(__file__).resolve().parents[3]  # core/tests/config → корень репозитория


def test_defaults_are_our_five_connectors() -> None:
    connectors = Config().connectors
    assert [c.id for c in connectors] == ["notes", "calc", "timers", "weather", "food"]
    for c in connectors:
        assert c.command == "uv"
        assert c.args == ["run", "--project", str(REPO / "connectors" / c.id), f"{c.id}-mcp"]
        assert c.enabled
        assert c.name
        assert Path(c.args[2]).is_absolute()
        assert (Path(c.args[2]) / "pyproject.toml").exists()
    weather = next(c for c in connectors if c.id == "weather")
    assert weather.env == {"WEATHER_PLACE": ""}
    assert all(c.env == {} for c in connectors if c.id != "weather")


def test_defaults_file_has_repo_path(tmp_path: Path) -> None:
    load_config(tmp_path / "config.yaml")
    text = (tmp_path / "config.defaults.yaml").read_text(encoding="utf-8")
    defaults = yaml.safe_load(text)
    assert defaults["connectors"][0]["args"][2] == str(REPO / "connectors" / "notes")


def test_owner_file_without_connectors_gets_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 3\nhistory:\n  max_turns: 5\n", encoding="utf-8")
    assert [c.id for c in load_config(path).connectors] == ["notes", "calc", "timers", "weather", "food"]


def test_owner_connectors_replace_list(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 3\nconnectors:\n  - id: my\n    name: Моё\n    command: /bin/my\n", encoding="utf-8"
    )
    (only,) = load_config(path).connectors
    assert only == ConnectorConfig(id="my", name="Моё", command="/bin/my")
    assert (only.args, only.env, only.enabled) == ([], {}, True)


@pytest.mark.parametrize(
    ("connectors", "fragment"),
    [
        ([{"id": "a", "name": "A", "command": "x"}, {"id": "a", "name": "B", "command": "y"}], "a"),
        ([{"id": "../up", "name": "A", "command": "x"}], "id"),
        ([{"id": "", "name": "A", "command": "x"}], "id"),
    ],
)
def test_bad_connectors_rejected(connectors: list[dict[str, object]], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        Config.model_validate({"connectors": connectors})


def test_patch_disables_connector(tmp_path: Path) -> None:
    store = ConfigFile(tmp_path / "config.yaml")
    store.load()
    connectors = [c.model_dump() for c in Config().connectors]
    connectors[0]["enabled"] = False
    merged = store.merge({"connectors": connectors})
    assert not merged.connectors[0].enabled
    with pytest.raises(ValueError, match="connectors"):
        store.merge({"connectors": [{"id": "a", "name": "A", "command": "x", "typo": 1}]})
