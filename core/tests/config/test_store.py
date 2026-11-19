from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, ConfigFile, load_config

MAC = "AA:BB:CC:DD:EE:FF"


def _store(tmp_path: Path, text: str | None = None) -> ConfigFile:
    path = tmp_path / "config.yaml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    store = ConfigFile(path)
    store.load()
    return store


def test_merge_deep_keeps_other_columns(tmp_path: Path) -> None:
    store = _store(tmp_path, f'version: 3\ndevices:\n  "{MAC}":\n    name: Старое\n')
    config = store.merge({"devices": {MAC: {"name": "Кухня"}}})
    assert config.devices[MAC].name == "Кухня"


def test_merge_keeps_other_devices(tmp_path: Path) -> None:
    store = _store(tmp_path, 'version: 3\ndevices:\n  "11:11":\n    name: Один\n')
    config = store.merge({"devices": {MAC: {"name": "Кухня"}}})
    assert config.devices["11:11"].name == "Один"
    assert config.devices[MAC].name == "Кухня"


def test_merge_list_replaced_whole(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.merge({"stages": []}).stages == []
    one = {"id": "a", "name": "A", "model": "m", "entry": True}
    assert [e.id for e in store.merge({"executors": [one]}).executors] == ["a"]


def test_null_resets_to_default(tmp_path: Path) -> None:
    store = _store(tmp_path, "version: 3\ntts:\n  kind: piper\n  voice: x\n")
    config = store.merge({"tts": None})
    store.save(config)
    assert "tts" not in yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert store.config.tts == Config().tts


def test_invalid_value_raises_and_file_untouched(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="port"):
        store.merge({"server": {"port": "x"}})
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before


def test_overridden_after_save(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.overridden() == []
    store.save(store.merge({"tts": {"kind": "piper"}}))
    assert store.overridden() == ["tts.kind"]
    assert ConfigFile(tmp_path / "config.yaml").load() == store.config


def test_overridden_device_and_lists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(store.merge({"devices": {MAC: {"name": "Кухня"}}, "stages": []}))
    keys = _store(tmp_path).overridden()
    assert f"devices.{MAC}.name" in keys
    store.save(store.merge({"executors": [{"id": "a", "name": "A", "model": "m", "entry": True}]}))
    assert "executors" in store.overridden()


def test_save_is_atomic_and_roundtrips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = store.merge({"tts": {"kind": "piper"}, "history": {}})
    store.save(config)
    assert sorted(p.name for p in tmp_path.iterdir() if "tmp" in p.name) == []
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8").startswith("# Настройки ядра")
    assert ConfigFile(tmp_path / "config.yaml").load() == config
    assert store.effective() == config.model_dump(mode="json")


def test_section(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert ConfigFile.section(store.config, "server") == store.effective()["server"]


def test_config_before_load_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        ConfigFile(tmp_path / "config.yaml").config  # noqa: B018


@pytest.mark.parametrize("version", ["99", "4", "abc", "true", "3.5", "1"])
def test_unknown_version_rejected_untouched(tmp_path: Path, version: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(f"version: {version}\ntts:\n  kind: piper\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="более новой версии"):
        load_config(path)
    assert path.read_text(encoding="utf-8") == before
    assert not path.with_name("config.yaml.bak").exists()


def test_version_in_patch_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="version"):
        store.merge({"version": 99})


def test_write_overrides_never_replaces_version(tmp_path: Path) -> None:
    from smartesp.config._files import write_overrides
    from smartesp.config.models import CONFIG_VERSION

    path = tmp_path / "config.yaml"
    write_overrides(path, {"version": 99, "tts": {"kind": "piper"}})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == CONFIG_VERSION
    load_config(path)


@pytest.mark.parametrize(
    ("patch", "key"),
    [
        ({"ttss": {"kind": "x"}}, "ttss"),
        ({"tts": {"kidn": "x"}}, "tts.kidn"),
        ({"devices": {MAC: {"nmae": "x"}}}, f"devices.{MAC}.nmae"),
        (
            {"executors": [{"id": "a", "name": "A", "model": "m", "entry": True, "modle": "x"}]},
            "executors[0].modle",
        ),
        ({"stages": [{"kind": "k", "tmeout": 1}]}, "stages[0].tmeout"),
    ],
)
def test_unknown_keys_rejected(tmp_path: Path, patch: dict[str, object], key: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(
        ValueError, match="неизвестный ключ настроек: " + key.replace("[", r"\[").replace("]", r"\]")
    ):
        store.merge(patch)


def test_new_device_id_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.merge({"devices": {"NEW:ID": {"name": "Зал"}}}).devices["NEW:ID"].name == "Зал"


def test_load_tolerates_unknown_keys(tmp_path: Path) -> None:
    store = _store(tmp_path, "version: 3\nfuture_key: 1\n")
    assert store.config == Config()


@pytest.mark.parametrize("patch", [[], None, "x", 5])
def test_non_dict_patch_is_value_error(tmp_path: Path, patch: object) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="словар"):
        store.merge(patch)  # type: ignore[arg-type]


TYPO = (
    "version: 3\nhistroy: {max_turns: 3}\ntts: {kidn: x, voice: baya}\ndevices:\n  A: {name: Зал, nmae: x}\n"
)


def test_unknown_key_in_file_does_not_block_patch(tmp_path: Path) -> None:
    store = _store(tmp_path, TYPO)
    config = store.merge({"tts": {"kind": "vosk", "voice": "female_1"}})
    assert (config.tts.kind, config.tts.voice) == ("vosk", "female_1")
    with pytest.raises(ValueError, match="неизвестный ключ настроек: tts.kidn"):
        store.merge({"tts": {"kidn": "y"}})  # в самой правке опечатка — по-прежнему отказ


def test_unknown_keys_in_file_are_warned_and_not_listed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path, TYPO)
    assert "histroy" in caplog.text and "tts.kidn" in caplog.text and "devices.A.nmae" in caplog.text
    assert sorted(store.overridden()) == ["devices.A.name", "tts.voice"]
    store.save(store.merge({}))
    assert "histroy" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_speech_defaults() -> None:
    assert Config().speech.proactive is True
    assert Config().speech.listen_after_question is True


def test_speech_patch_is_merged_and_unknown_key_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = store.merge({"speech": {"proactive": False}})
    assert config.speech.proactive is False
    assert config.speech.listen_after_question is True
    with pytest.raises(ValueError, match="speech.volume"):
        store.merge({"speech": {"volume": 3}})
