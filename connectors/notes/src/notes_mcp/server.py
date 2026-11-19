"""MCP-сервер заметок: сборка и запуск."""

import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import lists_tools, notes_tools

DATA_ENV = "SMARTESP_CONNECTOR_DATA"


def build_server(data_dir: Path, now: Callable[[], datetime] = datetime.now) -> MCPServer:
    """Собирает сервер, хранящий данные в `data_dir` (`now` — часы, подменяются в тестах)."""
    server = MCPServer("notes")
    lists_tools.register(server, data_dir)
    notes_tools.register(server, data_dir, now)
    return server


def main() -> None:
    """Запуск по stdio; папка данных — из `SMARTESP_CONNECTOR_DATA`."""
    data = os.environ.get(DATA_ENV, "").strip()
    if not data:
        sys.exit(f"notes-mcp: не задана переменная {DATA_ENV} — папка для данных коннектора.")
    build_server(Path(data)).run()
