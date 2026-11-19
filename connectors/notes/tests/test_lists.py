"""Тесты инструментов списков."""

import os
from pathlib import Path

import pytest

from .conftest import Caller


async def test_add_and_show(call: Caller, data_dir: Path) -> None:
    out = await call("list_add", {"list": "покупки", "items": ["молоко", "хлеб"]})
    assert out == "Добавила в «покупки»: молоко, хлеб."
    assert await call("list_show", {"list": "покупки"}) == "В списке «покупки»: молоко, хлеб."
    assert (data_dir / "home" / "lists" / "покупки.md").read_text() == "- молоко\n- хлеб\n"


async def test_show_empty_and_missing(call: Caller) -> None:
    assert await call("list_show", {"list": "покупки"}) == "Список «покупки» пуст."


async def test_name_normalized(call: Caller, data_dir: Path) -> None:
    await call("list_add", {"list": "  Покупки ", "items": ["сыр"]})
    await call("list_add", {"list": "покупки", "items": ["чай"]})
    assert await call("list_show", {"list": "ПОКУПКИ"}) == "В списке «покупки»: сыр, чай."
    await call("list_add", {"list": "Всё  для Ёлки", "items": ["шар"]})
    assert await call("list_show", {"list": "все для елки"}) == "В списке «все для елки»: шар."
    assert sorted(p.name for p in (data_dir / "home" / "lists").iterdir()) == [
        "все для елки.md",
        "покупки.md",
    ]


async def test_list_name_cannot_escape(call: Caller, data_dir: Path) -> None:
    await call("list_add", {"list": "../../x", "items": ["a"]})
    assert not (data_dir.parent / "x.md").exists()
    assert [p.name for p in data_dir.rglob("*.md")] == ["x.md"]
    assert (data_dir / "home" / "lists" / "x.md").exists()


async def test_person_name_cannot_escape(call: Caller, data_dir: Path) -> None:
    await call("list_add", {"list": "п", "items": ["a"]}, person="../x")
    assert not (data_dir.parent / "x").exists()
    assert (data_dir / "x" / "lists" / "п.md").exists()


async def test_empty_list_name(call: Caller) -> None:
    for tool, args in [("list_add", {"items": ["a"]}), ("list_show", {}), ("list_clear", {})]:
        assert await call(tool, {"list": "...", **args}) == "Не поняла, как назвать список."


async def test_add_empty_items(call: Caller) -> None:
    assert await call("list_add", {"list": "покупки", "items": ["", "  "]}) == "Нечего добавлять."


async def test_remove_partial_case_insensitive(call: Caller) -> None:
    await call("list_add", {"list": "покупки", "items": ["Молоко 2 л", "хлеб"]})
    out = await call("list_remove", {"list": "покупки", "items": ["МОЛОКО"]})
    assert out == "Вычеркнула из «покупки»: Молоко 2 л."
    assert await call("list_show", {"list": "покупки"}) == "В списке «покупки»: хлеб."


async def test_remove_exact_wins_over_partial(call: Caller) -> None:
    await call("list_add", {"list": "п", "items": ["молоко", "молоко 2 л"]})
    out = await call("list_remove", {"list": "п", "items": ["молоко"]})
    assert out == "Вычеркнула из «п»: молоко."
    assert await call("list_show", {"list": "п"}) == "В списке «п»: молоко 2 л."


async def test_remove_ambiguous_keeps_items(call: Caller) -> None:
    await call("list_add", {"list": "п", "items": ["молоко 1 л", "молоко 2 л"]})
    out = await call("list_remove", {"list": "п", "items": ["молоко"]})
    assert "не вычеркнула" in out.lower()
    assert "молоко 1 л" in out and "молоко 2 л" in out
    assert await call("list_show", {"list": "п"}) == "В списке «п»: молоко 1 л, молоко 2 л."


async def test_remove_not_found(call: Caller) -> None:
    await call("list_add", {"list": "п", "items": ["хлеб"]})
    out = await call("list_remove", {"list": "п", "items": ["сыр", "хлеб"]})
    assert "Вычеркнула из «п»: хлеб." in out
    assert "Не нашла: сыр." in out


async def test_clear_and_lists(call: Caller) -> None:
    assert await call("lists") == "Списков пока нет."
    await call("list_add", {"list": "покупки", "items": ["a"]})
    await call("list_add", {"list": "готовка", "items": ["b"]})
    assert await call("lists") == "Списки: готовка, покупки."
    assert await call("list_clear", {"list": "покупки"}) == "Список «покупки» очищен."
    assert await call("list_show", {"list": "покупки"}) == "Список «покупки» пуст."
    assert await call("lists") == "Списки: готовка."


async def test_persons_are_separate(call: Caller, data_dir: Path) -> None:
    await call("list_add", {"list": "покупки", "items": ["общее"]})
    await call("list_add", {"list": "покупки", "items": ["папино"]}, person="папа")
    assert await call("list_show", {"list": "покупки"}) == "В списке «покупки»: общее."
    assert await call("list_show", {"list": "покупки"}, person="папа") == "В списке «покупки»: папино."
    assert await call("list_show", {"list": "покупки"}, person="мама") == "Список «покупки» пуст."
    assert (data_dir / "папа" / "lists" / "покупки.md").exists()


async def test_atomic_write_keeps_file_on_error(
    call: Caller, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await call("list_add", {"list": "п", "items": ["хлеб"]})
    path = data_dir / "home" / "lists" / "п.md"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("диск")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(AssertionError):
        await call("list_add", {"list": "п", "items": ["сыр"]})
    monkeypatch.undo()
    assert path.read_text() == "- хлеб\n"
    assert [p.name for p in path.parent.iterdir()] == ["п.md"]
