"""MCP-сервер питания: сборка и запуск."""

import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

from . import log_tools, report_tools
from .off import OpenFoodFacts

DATA_ENV = "SMARTESP_CONNECTOR_DATA"


def build_server(
    data_dir: Path,
    now: Callable[[], datetime] = datetime.now,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MCPServer:
    """Собирает сервер с данными в `data_dir`.

    `now` — часы, `transport` — сеть для Open Food Facts; оба подменяются в тестах.
    """
    server = MCPServer("food")
    log_tools.register(server, data_dir, now, OpenFoodFacts(transport))
    report_tools.register(server, data_dir, now)
    return server


def main() -> None:
    """Запуск по stdio; папка данных — из `SMARTESP_CONNECTOR_DATA`."""
    data = os.environ.get(DATA_ENV, "").strip()
    if not data:
        sys.exit(f"food-mcp: не задана переменная {DATA_ENV} — папка для данных коннектора.")
    build_server(Path(data)).run()
