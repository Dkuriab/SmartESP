"""Тесты связей исполнителей в настройках."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, load_config
from smartesp.config.store import ConfigFile

GEMMA = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"
WHEN = "сложные рассуждения и расчёты, подробные объяснения общеизвестного (как устроено, почему так)"
OLD_WHEN = "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя"
OLD_DESCRIPTION = "большая модель: рассуждения, расчёты, подробные объяснения, знания"


def _ex(id_: str, *, entry: bool = False, to: list[str] | None = None) -> dict[str, object]:
    return {
        "id": id_,
        "name": id_.upper(),
        "model": "m",
        "entry": entry,
        "delegates": [{"to": t} for t in to or []],
    }


def test_defaults_are_dispatcher_and_big() -> None:
    dispatcher, big = Config().executors
    assert dispatcher.id == "dispatcher" and dispatcher.entry
    assert [(d.to, d.when) for d in dispatcher.delegates] == [("big", WHEN)]
    assert (big.id, big.name, big.model, big.entry) == ("big", "Большая модель", "deepseek-r1:8b", False)
    assert big.description == "большая модель: рассуждения, расчёты, подробные объяснения"
    assert big.system_prompt == (
        "Ты отвечаешь голосом через колонку: по-русски, без разметки и списков, связно, до 6–8 предложений."
    )
    assert big.delegates == []


@pytest.mark.parametrize(
    ("executors", "fragment"),
    [
        ([_ex("a", entry=True, to=["a"])], "a"),
        ([_ex("a", entry=True, to=["ghost"])], "ghost"),
        ([_ex("a", entry=True, to=["b", "b"]), _ex("b")], "b"),
        ([_ex("a", entry=True), _ex("a")], "a"),
    ],
)
def test_invalid_links_rejected(executors: list[dict[str, object]], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        Config.model_validate({"executors": executors})


def test_cycle_allowed() -> None:
    config = Config.model_validate({"executors": [_ex("a", entry=True, to=["b"]), _ex("b", to=["a"])]})
    assert [e.id for e in config.executors] == ["a", "b"]


def test_version_3_file_without_executors_gets_two(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 3\n", "utf-8")
    assert [e.id for e in load_config(path).executors] == ["dispatcher", "big"]


def test_owner_list_of_one_has_no_big(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"version": 3, "executors": [_ex("dispatcher", entry=True)]}), "utf-8")
    assert [e.id for e in load_config(path).executors] == ["dispatcher"]


def test_new_keys_known_in_patch(tmp_path: Path) -> None:
    store = ConfigFile(tmp_path / "config.yaml")
    ex = {**_ex("a", entry=True, to=["b"]), "description": "d"}
    ex["delegates"] = [{"to": "b", "when": "w"}]
    config = store.merge({"executors": [ex, _ex("b")]})
    assert config.executors[0].delegates[0].when == "w"
    bad = {**ex, "delegates": [{"to": "b", "wehn": "w"}]}
    with pytest.raises(ValueError, match=r"delegates\[0\]\.wehn"):
        store.merge({"executors": [bad, _ex("b")]})


def test_default_dispatcher_is_gpt_oss_with_low_reasoning() -> None:
    dispatcher, big = Config().executors
    assert (dispatcher.model, dispatcher.reasoning) == ("gpt-oss:20b", "low")
    assert big.reasoning == "off"


def test_reasoning_defaults_to_off_and_rejects_unknown_level() -> None:
    config = Config.model_validate({"executors": [_ex("a", entry=True)]})
    assert config.executors[0].reasoning == "off"
    with pytest.raises(ValueError, match="reasoning"):
        Config.model_validate({"executors": [{**_ex("a", entry=True), "reasoning": "max"}]})


def test_owner_model_choice_is_kept_and_untouched_default_changes(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    owner = [e.model_dump() for e in Config().executors]
    owner[0] = {k: v for k, v in owner[0].items() if k != "reasoning"}
    owner[0]["model"] = GEMMA
    path.write_text(yaml.safe_dump({"version": 4, "executors": owner}, allow_unicode=True), "utf-8")
    dispatcher = load_config(path).entry_executor()
    assert (dispatcher.model, dispatcher.reasoning) == (GEMMA, "off")
    untouched = tmp_path / "other.yaml"
    untouched.write_text("version: 4\n", "utf-8")
    assert load_config(untouched).entry_executor().model == "gpt-oss:20b"


def _v6_executors(old_prompt: str) -> list[dict[str, object]]:
    """Сохранённые владельцем исполнители версии 6: своя модель, тексты — прежние умолчания."""
    owner = [e.model_dump() for e in Config().executors]
    owner[0]["model"] = GEMMA
    owner[0]["system_prompt"] = old_prompt
    owner[0]["delegates"] = [{"to": "big", "when": OLD_WHEN}]
    owner[1]["description"] = OLD_DESCRIPTION
    return owner


def test_version_6_old_default_texts_become_new(tmp_path: Path) -> None:
    from smartesp.config.loader import _KNOWLEDGE_PROMPT  # pyright: ignore[reportPrivateUsage]
    from smartesp.config.models import DEFAULT_SYSTEM_PROMPT

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"version": 6, "executors": _v6_executors(_KNOWLEDGE_PROMPT)}), "utf-8")
    dispatcher, big = load_config(path).executors
    assert dispatcher.model == GEMMA  # выбор владельца сохранён
    assert dispatcher.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert [(d.to, d.when) for d in dispatcher.delegates] == [("big", WHEN)]
    assert big.description == "большая модель: рассуждения, расчёты, подробные объяснения"
    saved = yaml.safe_load(path.read_text("utf-8"))
    assert saved["version"] == 7 and (tmp_path / "config.yaml.bak").exists()


def test_version_6_owner_texts_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    owner = _v6_executors("Мой промпт")
    owner[0]["delegates"] = [{"to": "big", "when": "мои условия"}]
    owner[1]["description"] = "моё описание"
    path.write_text(yaml.safe_dump({"version": 6, "executors": owner}, allow_unicode=True), "utf-8")
    dispatcher, big = load_config(path).executors
    assert dispatcher.system_prompt == "Мой промпт"
    assert [(d.to, d.when) for d in dispatcher.delegates] == [("big", "мои условия")]
    assert big.description == "моё описание"


def test_version_6_keeps_owner_stage_choice(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 6\nstages:\n  - kind: clock\n", "utf-8")  # people владелец убрал сам
    assert [s.kind for s in load_config(path).stages] == ["clock"]
