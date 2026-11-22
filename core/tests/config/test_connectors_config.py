"""Тесты раздела connectors в настройках."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, ConfigFile, ConnectorConfig, load_config
from smartesp.config.connectors import DEFAULT_CLIENTS, DEFAULT_CONNECTORS

DEFAULT_IDS = [cid for cid, *_ in (*DEFAULT_CONNECTORS, *DEFAULT_CLIENTS)]

REPO = Path(__file__).resolve().parents[3]  # core/tests/config → корень репозитория


def test_defaults_are_our_connectors() -> None:
    connectors = Config().connectors
    ids = [
        "notes",
        "calc",
        "timers",
        "weather",
        "food",
        "mac_media",
        "claude_tasks",
        "web",
        "music",
        "telegram",
    ]
    assert [c.id for c in connectors] == ids
    client = connectors[-1]
    assert (client.kind, client.enabled) == (
        "client",
        False,
    )  # бот включает владелец (мог работать из терминала)
    assert client.args == ["run", "--project", "{repo}/clients/telegram", "telegram-bot"]
    assert "telegram-bot = " in (REPO / "clients" / "telegram" / "pyproject.toml").read_text(encoding="utf-8")
    connectors = connectors[:-1]
    for c in connectors:
        assert c.kind == "mcp"
        script = f"{c.id.replace('_', '-')}-mcp"
        assert c.command == "uv"
        assert c.args == ["run", "--project", f"{{repo}}/connectors/{c.id}", script]
        # задачам Клоду нужны папки владельца; mac_media владелец включает сам
        assert c.enabled == (c.id not in ("claude_tasks", "mac_media"))
        assert c.name
        project = Path(c.expanded().args[2])
        assert project == REPO / "connectors" / c.id
        assert f"{script} = " in (project / "pyproject.toml").read_text(encoding="utf-8")
    env = {c.id: c.env for c in connectors if c.env}
    assert env == {
        "weather": {"WEATHER_PLACE": ""},
        "claude_tasks": {"CLAUDE_TASK_FOLDERS": ""},
        "music": {"MUSIC_FOLDERS": "", "MUSIC_RADIO": "", "MUSIC_MAC_DEVICE": ""},
    }


def test_defaults_file_keeps_repo_placeholder(tmp_path: Path) -> None:
    # путь не закрепляется в настройках: перенос репозитория их не ломает
    load_config(tmp_path / "config.yaml")
    text = (tmp_path / "config.defaults.yaml").read_text(encoding="utf-8")
    defaults = yaml.safe_load(text)
    assert defaults["connectors"][0]["args"][2] == "{repo}/connectors/notes"


def test_expanded_replaces_placeholder_and_keeps_absolute_paths() -> None:
    custom = ConnectorConfig(
        id="x", name="X", command="{repo}/bin/x", args=["/abs/path", "{repo}"], env={"P": "{repo}/d"}
    )
    expanded = custom.expanded()
    assert expanded.command == f"{REPO}/bin/x"
    assert expanded.args == ["/abs/path", str(REPO)]
    assert expanded.env == {"P": f"{REPO}/d"}
    assert custom.args == ["/abs/path", "{repo}"]  # исходные настройки не меняются


def test_owner_file_without_connectors_gets_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 3\nhistory:\n  max_turns: 5\n", encoding="utf-8")
    assert [c.id for c in load_config(path).connectors] == [c.id for c in Config().connectors]


def test_owner_connector_with_new_id_is_added_after_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 4\nconnectors:\n  - id: my\n    name: Моё\n    command: /bin/my\n", encoding="utf-8"
    )
    connectors = load_config(path).connectors
    assert [c.id for c in connectors] == [*DEFAULT_IDS, "my"]
    assert connectors[-1] == ConnectorConfig(id="my", name="Моё", command="/bin/my")


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
    first = Config().connectors[0].id
    merged = store.merge({"connectors": [{"id": first, "enabled": False}]})
    assert not merged.connectors[0].enabled
    with pytest.raises(ValueError, match="connectors"):
        store.merge({"connectors": [{"id": "a", "name": "A", "command": "x", "typo": 1}]})
