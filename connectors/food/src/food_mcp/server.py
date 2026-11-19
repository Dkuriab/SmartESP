"""MCP-сервер питания: сборка и запуск."""

import os
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

from . import log_tools, report_tools
from .barcode_list import BarcodeList
from .lookup import Lookups
from .off import OpenFoodFacts

DATA_ENV = "SMARTESP_CONNECTOR_DATA"
OFF_ENV = "FOOD_OFF"  # «1» — включить Open Food Facts (из России без VPN не открывается)


def build_server(
    data_dir: Path,
    now: Callable[[], datetime] = datetime.now,
    transport: httpx.AsyncBaseTransport | None = None,
    barcode_transport: httpx.AsyncBaseTransport | None = None,
    off_enabled: bool | None = None,
    barcode_clock: Callable[[], float] = time.monotonic,
) -> MCPServer:
    """Собирает сервер с данными в `data_dir`.

    `now` — часы, `transport` и `barcode_transport` — сеть для Open Food Facts и barcode-list.ru,
    `barcode_clock` — часы для паузы между запросами; всё это подменяется в тестах.
    `off_enabled`: None — по переменной `FOOD_OFF=1`.
    """
    if off_enabled is None:
        off_enabled = os.environ.get(OFF_ENV, "").strip() == "1"
    lookups = Lookups(
        BarcodeList(barcode_transport, barcode_clock),
        data_dir,
        OpenFoodFacts(transport) if off_enabled else None,
    )
    server = MCPServer("food")
    log_tools.register(server, data_dir, now, lookups)
    report_tools.register(server, data_dir, now)
    return server


def main() -> None:
    """Запуск по stdio; папка данных — из `SMARTESP_CONNECTOR_DATA`."""
    data = os.environ.get(DATA_ENV, "").strip()
    if not data:
        sys.exit(f"food-mcp: не задана переменная {DATA_ENV} — папка для данных коннектора.")
    build_server(Path(data)).run()
