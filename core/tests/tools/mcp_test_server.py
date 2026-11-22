"""Маленький MCP-сервер для тестов хаба (stdio).

Запуск: `python mcp_test_server.py [режим]`. Режимы:
- без режима — обычный сервер;
- `garbage` — перед запуском печатает мусор в stdout;
- `hang` — никогда не отвечает и не читает stdin (не запускается);
- `exit` — сразу завершается с ошибкой;
- `stubborn` — работает как обычный, но не выходит ни по концу stdin, ни по SIGTERM.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import time
from pathlib import Path

from mcp import types
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer("test")
_background: set[asyncio.Task[None]] = set()  # фоновые задачи (держим ссылки)


@server.tool(description="Повторяет текст")
def echo(text: str) -> str:
    return text


@server.tool(description="Номер процесса")
def pid() -> str:
    return str(os.getpid())


@server.tool(description="Кто просит (из _meta.person)")
def whoami(ctx: Context) -> str:
    meta = ctx.request_context.meta or {}
    device, name = meta.get("device"), meta.get("person_name")
    who = str(meta.get("person", "никто")) + (f" ({name})" if name else "")
    return who + (f"@{device}" if device else "")


@server.tool(description="Папка данных и переменная окружения")
def env(name: str) -> str:
    data = os.environ.get("SMARTESP_CONNECTOR_DATA", "")
    return f"{data}|{Path(data).is_dir()}|{os.environ.get(name, '')}"


@server.tool(description="Спит секунды")
async def sleep(seconds: float) -> str:
    await asyncio.sleep(seconds)
    return "проснулся"


@server.tool(description="Ошибка инструмента")
def fail() -> str:
    raise ValueError("сломалось")


@server.tool(description="Понятная ошибка для модели (ToolError)")
def refuse() -> str:
    raise ToolError("Место не задано: укажите город.")


@server.tool(description="Падает весь процесс")
def crash() -> str:
    os._exit(3)


@server.tool(description="Объявление через уведомление журнала")
async def announce(text: str, person: str | None, ctx: Context) -> str:
    data = {"type": "announce", "text": text, "person": person}
    await ctx.log("info", data, logger_name="smartesp")  # pyright: ignore[reportDeprecated]
    return "объявил"


@server.tool(description="Задача «В работе» через уведомление журнала")
async def task(task_id: str, title: str, status: str, ctx: Context) -> str:
    data = {"type": "task", "id": task_id, "title": title, "status": status, "eta": 1800000000}
    await ctx.log("info", data, logger_name="smartesp")  # pyright: ignore[reportDeprecated]
    return "сообщил"


@server.tool(description="Объявление позже, вне вызова инструмента (как таймер)")
async def announce_later(text: str, seconds: float, ctx: Context) -> str:
    session = ctx.request_context.session

    async def later() -> None:
        await asyncio.sleep(seconds)
        data = {"type": "announce", "text": text, "person": None}
        params = types.LoggingMessageNotificationParams(level="info", logger="smartesp", data=data)
        await session.send_notification(types.LoggingMessageNotification(params=params))

    _background.add(asyncio.create_task(later()))
    return "объявлю позже"


LONG_TOOL = "l" * 63  # с префиксом `b_` длиннее 64 символов


@server.tool(name="delegate", description="Совпадает с инструментом ядра")
def delegate_tool() -> str:
    return "делегат коннектора"


@server.tool(name="notes.add", description="Имя с точкой")
def dotted() -> str:
    return "с точкой"


@server.tool(name=LONG_TOOL, description="Длинное имя; возвращает номер процесса")
def long_tool() -> str:
    return str(os.getpid())


@server.tool(description="Обычная запись журнала")
async def log(text: str, ctx: Context) -> str:
    await ctx.log("warning", text, logger_name="other")  # pyright: ignore[reportDeprecated]
    return "записал"


def main() -> None:
    """Запускает сервер в выбранном режиме; номер процесса пишет в папку данных."""
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = os.environ.get("SMARTESP_CONNECTOR_DATA")
    if data:
        (Path(data) / "pid").write_text(str(os.getpid()))
    if mode == "exit":
        sys.exit(2)
    if mode == "hang":
        while True:
            time.sleep(60)
    if mode == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        threading.Thread(target=lambda: time.sleep(3600)).start()  # не даёт процессу выйти
    if mode == "garbage":
        print("это не JSON", flush=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
