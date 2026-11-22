"""Настройки бота: чтение TOML, значения по умолчанию, понятные ошибки."""

from pathlib import Path

import pytest

from telegram_bot.settings import DEFAULT_CORE_URL, SettingsError, load_settings

VALID = """
[telegram]
bot_token = "42:secret"

[core]
url = "http://192.168.1.10:8765/"
token = "core-token"

[users]
111 = "Аня"
222 = "Борис"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_all_fields(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, VALID))
    assert settings.bot_token == "42:secret"
    assert settings.core_url == "http://192.168.1.10:8765"  # без хвостового «/»
    assert settings.core_token == "core-token"
    assert settings.users == {111: "Аня", 222: "Борис"}


def test_core_url_defaults_to_local_core(tmp_path: Path) -> None:
    text = VALID.replace('url = "http://192.168.1.10:8765/"\n', "")
    assert load_settings(write(tmp_path, text)).core_url == DEFAULT_CORE_URL == "http://127.0.0.1:8765"


def test_missing_file_names_the_example(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="settings.example.toml"):
        load_settings(tmp_path / "settings.toml")


def test_broken_toml(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="TOML"):
        load_settings(write(tmp_path, "[telegram\n"))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('bot_token = "42:secret"', 'bot_token = ""', "telegram.bot_token"),
        ('token = "core-token"', 'token = ""', "core.token"),
        ('url = "http://192.168.1.10:8765/"', 'url = "ftp://x"', "core.url"),
        ('111 = "Аня"\n222 = "Борис"', "", "users"),
        ('111 = "Аня"', 'abc = "Аня"', "user_id"),
        ('111 = "Аня"', '111 = ""', "111"),
        ('111 = "Аня"', "111 = 5", "111"),
    ],
)
def test_invalid_values(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in VALID
    with pytest.raises(SettingsError, match=message):
        load_settings(write(tmp_path, VALID.replace(old, new)))


def test_example_has_same_names_and_empty_secrets() -> None:
    example = Path(__file__).parent.parent / "settings.example.toml"
    text = example.read_text(encoding="utf-8")
    assert 'bot_token = ""' in text
    assert 'token = ""' in text
    assert f'url = "{DEFAULT_CORE_URL}"' in text
    assert "[users]" in text


def test_env_from_core_overrides_file_and_allows_no_file(tmp_path: Path) -> None:
    env = {
        "SMARTESP_URL": "http://127.0.0.1:8765",
        "SMARTESP_TOKEN": "core-token",
        "TELEGRAM_BOT_TOKEN": "123:AA",
        "TELEGRAM_USERS": "111=Данила; 222=Аня;",
    }
    settings = load_settings(tmp_path / "нет.toml", env)
    assert (settings.bot_token, settings.core_token, settings.managed) == ("123:AA", "core-token", True)
    assert settings.users == {111: "Данила", 222: "Аня"}
    empty = load_settings(tmp_path / "нет.toml", {**env, "TELEGRAM_USERS": ""})
    assert empty.users == {}  # от ядра: людей добавят из приложения
    with pytest.raises(SettingsError, match="в приложении"):
        load_settings(tmp_path / "нет.toml", {**env, "TELEGRAM_BOT_TOKEN": ""})
    with pytest.raises(SettingsError, match="user_id=имя"):
        load_settings(tmp_path / "нет.toml", {**env, "TELEGRAM_USERS": "Аня"})


def test_file_fills_what_env_leaves_empty(tmp_path: Path) -> None:
    settings = load_settings(
        write(tmp_path, VALID), {"SMARTESP_URL": "http://127.0.0.1:9000", "SMARTESP_TOKEN": "t"}
    )
    assert settings.core_url == "http://127.0.0.1:9000" and settings.core_token == "t"
    assert settings.bot_token and settings.users  # токен бота и люди — из файла
