"""Тесты связей исполнителей в настройках."""

from pathlib import Path

import pytest
import yaml

from smartesp.config import Config, load_config
from smartesp.config.store import ConfigFile

WHEN = "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя"


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
    assert big.description == "большая модель: рассуждения, расчёты, подробные объяснения, знания"
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


def test_reasoning_defaults_to_off_and_rejects_unknown_level() -> None:
    config = Config.model_validate({"executors": [_ex("a", entry=True)]})
    assert config.executors[0].reasoning == "off"
    with pytest.raises(ValueError, match="reasoning"):
        Config.model_validate({"executors": [{**_ex("a", entry=True), "reasoning": "max"}]})
