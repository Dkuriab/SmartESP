"""Тесты: в config.yaml только изменения владельца, умолчания — из кода."""

from pathlib import Path

import yaml

from smartesp.config import Config, load_config

OLD_PROMPT = (
    "Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен."
)


def legacy_dump(
    prompt: str = OLD_PROMPT, devices: dict[str, dict[str, str]] | None = None
) -> dict[str, object]:
    """Файл, который писали прежние версии: все настройки целиком, без version."""
    return {
        "server": {"host": "0.0.0.0", "port": 8765},
        "devices": devices or {},
        "arbitration": {"window_ms": 300, "late_ms": 1500},
        "stt": {"kind": "mlx_whisper", "model": "mlx-community/whisper-large-v3-turbo", "language": "ru"},
        "tts": {"kind": "piper", "voice": "ru_RU-irina-medium"},
        "executors": [
            {
                "id": "dispatcher",
                "name": "Диспетчер",
                "kind": "ollama",
                "model": "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive",
                "entry": True,
                "system_prompt": prompt,
                "keep_alive": "24h",
            }
        ],
        "stages": [],
        "history": {"max_turns": 10, "max_age_s": 300},
    }


def write(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")


def read(path: Path) -> object:
    return yaml.safe_load(path.read_text("utf-8"))


def test_new_file_holds_no_settings_and_defaults_file_is_written(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    assert load_config(path) == Config()
    assert read(path) == {"version": 3}
    defaults = read(tmp_path / "config.defaults.yaml")
    assert isinstance(defaults, dict)
    assert defaults["server"] == {"host": "0.0.0.0", "port": 8765}


def test_partial_file_is_merged_with_code_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 3, "devices": {"AA:BB:CC:DD:EE:FF": {"name": "Кухня"}}})
    config = load_config(path)
    assert config.devices["AA:BB:CC:DD:EE:FF"].name == "Кухня"
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock"]
    assert read(path) == {"version": 3, "devices": {"AA:BB:CC:DD:EE:FF": {"name": "Кухня"}}}


def test_legacy_full_dump_is_pruned_to_owner_changes(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump(devices={"1C:DB:D4:4A:91:D0": {"name": "Кухня"}}))
    config = load_config(path)
    assert read(path) == {"version": 3, "devices": {"1C:DB:D4:4A:91:D0": {"name": "Кухня"}}}
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock"]
    assert config.entry_executor().system_prompt == Config().entry_executor().system_prompt
    assert (tmp_path / "config.yaml.bak").exists()


def test_legacy_untouched_dump_becomes_empty(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump())
    assert load_config(path) == Config()
    assert read(path) == {"version": 3}


def test_legacy_custom_prompt_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump(prompt="Мой промпт."))
    config = load_config(path)
    assert config.entry_executor().system_prompt == "Мой промпт."
    saved = read(path)
    assert isinstance(saved, dict)
    assert "executors" in saved
    assert "stages" not in saved


def test_current_file_is_not_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    text = "version: 3\n# мой комментарий\nhistory:\n  max_turns: 4\n"
    path.write_text(text, "utf-8")
    assert load_config(path).history.max_turns == 4
    assert path.read_text("utf-8") == text


def test_legacy_default_tts_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump())
    config = load_config(path)
    assert "tts" not in read(path)  # type: ignore[operator]
    assert config.tts.kind == "silero"


def test_legacy_custom_tts_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    data = legacy_dump()
    data["tts"] = {"kind": "piper", "voice": "ru_RU-denis-medium"}
    write(path, data)
    config = load_config(path)
    assert config.tts == Config().tts.model_copy(update={"kind": "piper", "voice": "ru_RU-denis-medium"})
    assert read(path) == {"version": 3, "tts": {"kind": "piper", "voice": "ru_RU-denis-medium"}}


def test_current_file_with_explicit_piper_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 3, "tts": {"kind": "piper"}})
    assert load_config(path).tts.kind == "piper"
    assert read(path) == {"version": 3, "tts": {"kind": "piper"}}


def test_v2_tts_without_kind_becomes_piper(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 2, "tts": {"voice": "ru_RU-denis-medium"}})
    config = load_config(path)
    assert (config.tts.kind, config.tts.voice) == ("piper", "ru_RU-denis-medium")
    assert read(path) == {"version": 3, "tts": {"kind": "piper", "voice": "ru_RU-denis-medium"}}
    assert (tmp_path / "config.yaml.bak").exists()


def test_v2_without_tts_gets_new_default_and_version(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 2, "history": {"max_turns": 4}})
    config = load_config(path)
    assert config.tts.kind == "silero"
    assert read(path) == {"version": 3, "history": {"max_turns": 4}}
    assert (tmp_path / "config.yaml.bak").exists()


def test_defaults_contain_new_prompt(tmp_path: Path) -> None:
    prompt = Config().entry_executor().system_prompt
    assert prompt.startswith("Тебя зовут Кузя. ")
    assert OLD_PROMPT in prompt


def test_legacy_whisper_variant_prompt_is_pruned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    whisper = (
        OLD_PROMPT + " Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]."
        " Во всех остальных случаях никаких меток не пиши."
    )
    write(path, legacy_dump(prompt=whisper))
    assert load_config(path) == Config()
    assert read(path) == {"version": 3}


def test_v3_without_executors_gets_new_prompt(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 3, "history": {"max_turns": 4}})
    assert load_config(path).entry_executor().system_prompt.startswith("Тебя зовут Кузя.")


def test_legacy_kuzya_prompt_without_honesty_rule_is_pruned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    kuzya = (
        "Тебя зовут Кузя. Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
        "без разметки, списков и эмодзи — ответ будет озвучен."
    )
    write(path, legacy_dump(prompt=kuzya))
    config = load_config(path)
    assert config == Config() and "У меня нет доступа" in config.entry_executor().system_prompt
    assert read(path) == {"version": 3}


def test_default_prompt_has_honesty_rule() -> None:
    prompt = Config().entry_executor().system_prompt
    assert "Не выдумывай" in prompt and "У меня нет доступа" in prompt and len(prompt) < 600
