"""MCP-сервер задач для Claude Code: инструменты, объявления о конце задач, запуск по stdio."""

import logging
import os
import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from claude_tasks_mcp import phrases
from claude_tasks_mcp.announcer import Announcer
from claude_tasks_mcp.folders import FolderError, resolve_folder
from claude_tasks_mcp.manager import Manager, TaskError
from claude_tasks_mcp.runner import ClaudeRunner, Runner
from claude_tasks_mcp.settings import Settings, load_settings
from claude_tasks_mcp.store import Store, person_folder

DATA_ENV = "SMARTESP_CONNECTOR_DATA"
MAX_RUNNING = 2
RECENT = 5

logger = logging.getLogger(__name__)


def _person(ctx: Context) -> str | None:
    """Человек из `_meta.person` вызова; не строка или нет — общее «дом»."""
    meta: dict[str, Any] = dict(ctx.request_context.meta or {})
    person = meta.get("person")
    if not isinstance(person, str):
        return None
    try:
        person_folder(person)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return person


def _local_now() -> datetime:
    return datetime.now().astimezone()


def build_server(
    settings: Settings,
    data_dir: Path,
    *,
    runner: Runner | None = None,
    now: Callable[[], datetime] = _local_now,
    max_running: int = MAX_RUNNING,
) -> MCPServer[Any]:
    """Собирает сервер над папкой данных `data_dir`; `runner` и `now` — подмена для тестов."""
    announcer = Announcer()
    manager = Manager(
        Store(data_dir),
        runner or ClaudeRunner(settings.claude_bin, settings.tools, settings.env_passthrough),
        announcer.announce,
        timeout_s=settings.timeout_s,
        max_running=max_running,
        now=now,
    )

    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncGenerator[dict[str, Any]]:
        manager.load()
        try:
            yield {}
        finally:
            await manager.aclose()

    server: MCPServer[Any] = MCPServer(
        "claude_tasks",
        instructions="Задачи для Клода (Claude Code) на Mac в разрешённых папках. Готовое объявляется вслух.",
        lifespan=lifespan,
        middleware=[announcer],
    )
    _add_tools(server, manager, settings, now)
    return server


def _add_tools(
    server: MCPServer[Any], manager: Manager, settings: Settings, now: Callable[[], datetime]
) -> None:
    """Регистрирует инструменты (`async def` — менеджер меняется только в цикле событий)."""

    @server.tool(
        structured_output=False,
        description="Передать задачу Клоду (Claude Code) в фоне. Пример: «почини тесты ядра», «smartesp».",
    )
    async def task_start(
        ctx: Context,
        task: Annotated[str, Field(description="Что сделать, своими словами")],
        folder: Annotated[str, Field(description="Имя разрешённой папки; пусто — папка по умолчанию")] = "",
    ) -> str:
        if not task.strip():
            raise ToolError("Не сказано, что сделать.")
        try:
            label, path = resolve_folder(settings.folders, folder)
            record = manager.start(_person(ctx), task.strip(), label, path)
        except (FolderError, TaskError) as exc:
            raise ToolError(str(exc)) from None
        return phrases.started_text(record)

    @server.tool(
        structured_output=False, description="Как идёт задача Клода: идёт, готово или ошибка, и сколько."
    )
    async def task_status(
        ctx: Context,
        name: Annotated[str, Field(description="Имя задачи или его часть; пусто — последняя")] = "",
    ) -> str:
        person = _person(ctx)
        return _answer(lambda: phrases.status_text(manager.find(person, name), now()))

    @server.tool(structured_output=False, description="Последние 5 задач Клода и их состояние.")
    async def tasks(ctx: Context) -> str:
        return phrases.list_text(manager.recent(_person(ctx), RECENT), now())

    @server.tool(structured_output=False, description="Что ответил Клод по задаче: короткий итог.")
    async def task_result(
        ctx: Context,
        name: Annotated[str, Field(description="Имя задачи или его часть; пусто — последняя")] = "",
    ) -> str:
        person = _person(ctx)
        return _answer(lambda: phrases.result_text(manager.find(person, name)))

    @server.tool(structured_output=False, description="Отменить задачу Клода по имени.")
    async def task_cancel(
        ctx: Context,
        name: Annotated[str, Field(description="Имя задачи или его часть")],
    ) -> str:
        person = _person(ctx)
        return _answer(lambda: phrases.cancel_text(*manager.cancel(person, name)))


def _answer(make: Callable[[], str]) -> str:
    """Ответ про задачу; «нет такой» или «уточни» — тоже обычный ответ, а не ошибка."""
    try:
        return make()
    except TaskError as exc:
        return str(exc)


def main() -> None:
    """Запуск коннектора по stdio; папка данных — из SMARTESP_CONNECTOR_DATA, настройки — из окружения."""
    data = os.environ.get(DATA_ENV, "").strip()
    if not data:
        raise SystemExit(f"claude-tasks-mcp: не задана переменная {DATA_ENV} — папка для данных коннектора.")
    data_dir = Path(data)
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(os.environ)
    if not settings.folders:
        logger.warning("CLAUDE_TASK_FOLDERS не задана: задачи запускать будет негде")
    build_server(settings, data_dir).run("stdio")


if __name__ == "__main__":
    sys.exit(main())
