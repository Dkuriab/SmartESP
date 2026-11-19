"""Тесты сборки сервера: набор инструментов и запуск без папки данных."""

from pathlib import Path

import pytest
from mcp.client import Client

from notes_mcp.server import DATA_ENV, build_server, main


async def test_tool_names(data_dir: Path) -> None:
    async with Client(build_server(data_dir)) as client:
        tools = await client.list_tools()
    assert sorted(t.name for t in tools.tools) == sorted(
        [
            "list_add",
            "list_show",
            "list_remove",
            "list_clear",
            "lists",
            "note_add",
            "notes_find",
            "note_delete",
        ]
    )
    assert all(t.description for t in tools.tools)


def test_main_requires_data_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert DATA_ENV in str(exc.value)
