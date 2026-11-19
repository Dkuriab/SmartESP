"""Тесты модуля config."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, DeviceConfig, data_dir, load_config


def test_missing_file_creates_default(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    config = load_config(path)
    assert path.exists()
    assert config.entry_executor().id == "dispatcher"
    assert config.server.port == 8765
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock"]


def test_default_file_has_quoted_mac_example_and_loads(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    load_config(path)
    text = path.read_text("utf-8")
    assert '#   "AA:BB:CC:DD:EE:FF":' in text
    assert load_config(path) == Config()


def test_quoted_mac_device_key(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text('devices:\n  "AA:BB:CC:DD:EE:FF":\n    name: Кухня\n', "utf-8")
    assert load_config(path).devices["AA:BB:CC:DD:EE:FF"].name == "Кухня"


def test_broken_yaml_gives_value_error_with_path(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("server: [\n", "utf-8")
    with pytest.raises(ValueError, match="ошибка YAML") as info:
        load_config(path)
    assert str(path) in str(info.value)


def test_unreadable_file_gives_value_error_with_path(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.mkdir()  # вместо файла — папка: чтение падает с OSError
    with pytest.raises(ValueError, match="не удалось прочитать") as info:
        load_config(path)
    assert str(path) in str(info.value)


def test_roundtrip_yaml_unicode(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    config = Config(devices={"esp1": DeviceConfig(name="Кухня")})
    path.write_text(yaml.safe_dump(config.model_dump(), allow_unicode=True, sort_keys=False), "utf-8")
    assert "Кухня" in path.read_text("utf-8")
    assert load_config(path).devices["esp1"].name == "Кухня"


def test_two_entry_executors_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    executor = {"id": "a", "name": "A", "model": "m", "entry": True}
    path.write_text(yaml.safe_dump({"executors": [executor, {**executor, "id": "b"}]}), "utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_no_entry_executor_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"executors": [{"id": "a", "name": "A", "model": "m"}]}), "utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_smartesp_home_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SMARTESP_HOME", str(tmp_path))
    assert data_dir() == tmp_path
