"""Тесты сборки сервера и хранилища: набор инструментов, запуск без папки данных, атомарность."""

import os
from pathlib import Path

import pytest
from mcp.client import Client

from food_mcp.server import DATA_ENV, build_server, main
from food_mcp.storage import write_atomic


async def test_tool_names(data_dir: Path) -> None:
    async with Client(build_server(data_dir)) as client:
        tools = await client.list_tools()
    assert sorted(t.name for t in tools.tools) == sorted(
        ["food_log", "product_add", "food_today", "food_summary", "food_undo", "food_find"]
    )
    assert all(t.description for t in tools.tools)


async def test_food_log_hints_whole_choice_and_only_said_time(data_dir: Path) -> None:
    async with Client(build_server(data_dir)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    props = tools["food_log"].input_schema["properties"]
    assert "выбранный вариант целиком: «гречка варёная»" in props["what"]["description"]
    assert "только если человек сам сказал" in props["when"]["description"]


def test_main_requires_data_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert DATA_ENV in str(exc.value)


def test_write_atomic_keeps_old_file_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "a" / "products.json"
    write_atomic(path, "старое")

    def boom(src: str, dst: str) -> None:
        raise OSError("диск")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_atomic(path, "новое")
    assert path.read_text(encoding="utf-8") == "старое"
    assert [p.name for p in path.parent.iterdir()] == ["products.json"]
