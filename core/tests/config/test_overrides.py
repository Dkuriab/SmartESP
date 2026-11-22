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
    assert read(path) == {"version": 6}
    defaults = read(tmp_path / "config.defaults.yaml")
    assert isinstance(defaults, dict)
    assert defaults["server"] == {"host": "0.0.0.0", "port": 8765}


def test_partial_file_is_merged_with_code_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 6, "devices": {"AA:BB:CC:DD:EE:FF": {"name": "Кухня"}}})
    config = load_config(path)
    assert config.devices["AA:BB:CC:DD:EE:FF"].name == "Кухня"
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock", "system", "people"]
    assert read(path) == {"version": 6, "devices": {"AA:BB:CC:DD:EE:FF": {"name": "Кухня"}}}


def test_legacy_full_dump_is_pruned_to_owner_changes(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump(devices={"1C:DB:D4:4A:91:D0": {"name": "Кухня"}}))
    config = load_config(path)
    assert read(path) == {"version": 6, "devices": {"1C:DB:D4:4A:91:D0": {"name": "Кухня"}}}
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock", "system", "people"]
    assert config.entry_executor().system_prompt == Config().entry_executor().system_prompt
    assert (tmp_path / "config.yaml.bak").exists()


def test_legacy_untouched_dump_becomes_empty(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, legacy_dump())
    assert load_config(path) == Config()
    assert read(path) == {"version": 6}


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
    text = "version: 6\n# мой комментарий\nhistory:\n  max_turns: 4\n"
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
    assert read(path) == {"version": 6, "tts": {"kind": "piper", "voice": "ru_RU-denis-medium"}}


def test_current_file_with_explicit_piper_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 6, "tts": {"kind": "piper"}})
    assert load_config(path).tts.kind == "piper"
    assert read(path) == {"version": 6, "tts": {"kind": "piper"}}


def test_v2_tts_without_kind_becomes_piper(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 2, "tts": {"voice": "ru_RU-denis-medium"}})
    config = load_config(path)
    assert (config.tts.kind, config.tts.voice) == ("piper", "ru_RU-denis-medium")
    assert read(path) == {"version": 6, "tts": {"kind": "piper", "voice": "ru_RU-denis-medium"}}
    assert (tmp_path / "config.yaml.bak").exists()


def test_v2_without_tts_gets_new_default_and_version(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 2, "history": {"max_turns": 4}})
    config = load_config(path)
    assert config.tts.kind == "silero"
    assert read(path) == {"version": 6, "history": {"max_turns": 4}}
    assert (tmp_path / "config.yaml.bak").exists()


def test_defaults_contain_new_prompt(tmp_path: Path) -> None:
    prompt = Config().entry_executor().system_prompt
    assert prompt.startswith("Тебя зовут Кузя. ")
    assert "Пока!" in prompt and "Не задавай вопросов в конце" in prompt


def test_legacy_whisper_variant_prompt_is_pruned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    whisper = (
        OLD_PROMPT + " Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]."
        " Во всех остальных случаях никаких меток не пиши."
    )
    write(path, legacy_dump(prompt=whisper))
    assert load_config(path) == Config()
    assert read(path) == {"version": 6}


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
    assert config == Config() and "не выдумывай" in config.entry_executor().system_prompt
    assert read(path) == {"version": 6}


def test_legacy_no_access_prompt_is_pruned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    no_access = (
        "Тебя зовут Кузя. Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
        "без разметки, списков и эмодзи — ответ будет озвучен."
        " Ты знаешь только то, что есть в сообщении, в пометках и в ответах инструментов."
        " Не выдумывай время, погоду, новости и состояние устройств."
        " Нет данных или инструмента — скажи: «У меня нет доступа к …»."
        " Не говори, что что-то сделал, если инструмент этого не сделал."
    )
    write(path, legacy_dump(prompt=no_access))
    assert load_config(path) == Config()
    assert read(path) == {"version": 6}


def test_default_prompt_has_honesty_rule_but_no_push_to_no_access() -> None:
    prompt = Config().entry_executor().system_prompt
    assert "не выдумывай" in prompt and "только если инструмент это сделал" in prompt and len(prompt) < 1500
    # «нет доступа» — только правило ядра для действий и данных; общие знания — как обычно
    assert "нет доступа" not in prompt and "знаешь только" not in prompt


def test_legacy_wave3_prompt_is_pruned(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    wave3 = (
        "Тебя зовут Кузя. Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
        "без разметки, списков и эмодзи — ответ будет озвучен."
        " Время, погоду, новости и состояние устройств бери только из сообщения, пометок и ответов"
        " инструментов — не выдумывай их."
        " Не говори, что что-то сделал, если инструмент этого не сделал."
    )
    write(path, legacy_dump(prompt=wave3))
    assert load_config(path) == Config()


def test_v3_explicit_stages_get_clock_system_and_people_once(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 3, "stages": [{"kind": "whisper_detect"}]})
    config = load_config(path)
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock", "system", "people"]
    stages = [{"kind": "whisper_detect"}, {"kind": "clock"}, {"kind": "system"}, {"kind": "people"}]
    assert read(path) == {"version": 6, "stages": stages}
    assert (tmp_path / "config.yaml.bak").exists()


def test_v4_without_clock_gets_only_system_and_people(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 4, "stages": [{"kind": "whisper_detect"}]})
    assert [s.kind for s in load_config(path).stages] == ["whisper_detect", "system", "people"]
    stages = [{"kind": "whisper_detect"}, {"kind": "system"}, {"kind": "people"}]
    assert read(path) == {"version": 6, "stages": stages}
    assert (tmp_path / "config.yaml.bak").exists()


def test_v5_without_system_gets_only_people(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 5, "stages": [{"kind": "clock"}]})
    assert [s.kind for s in load_config(path).stages] == ["clock", "people"]
    assert read(path) == {"version": 6, "stages": [{"kind": "clock"}, {"kind": "people"}]}
    assert (tmp_path / "config.yaml.bak").exists()


def test_v6_without_people_stays_without(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 6, "stages": [{"kind": "clock"}]})
    assert [s.kind for s in load_config(path).stages] == ["clock"]
    assert read(path) == {"version": 6, "stages": [{"kind": "clock"}]}


def test_v2_migrates_through_to_v6(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 2, "tts": {"voice": "x"}, "stages": [{"kind": "whisper_detect"}]})
    config = load_config(path)
    assert config.tts.kind == "piper"
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock", "system", "people"]
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == 6


def test_v3_without_stages_unaffected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write(path, {"version": 3, "history": {"max_turns": 4}})
    config = load_config(path)
    assert [s.kind for s in config.stages] == ["whisper_detect", "clock", "system", "people"]
    assert read(path) == {"version": 6, "history": {"max_turns": 4}}
