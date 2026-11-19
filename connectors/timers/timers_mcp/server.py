"""MCP-сервер таймеров: инструменты, фоновая проверка срабатываний, запуск по stdio."""

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from timers_mcp import phrases
from timers_mcp.announcer import Announcer
from timers_mcp.board import CANCEL_ALL, Board
from timers_mcp.clock import Clock, SystemClock
from timers_mcp.store import Store, person_folder
from timers_mcp.times import parse_reminder_time

DATA_ENV = "SMARTESP_CONNECTOR_DATA"
MAX_MINUTES = 7 * 24 * 60
POLL = timedelta(seconds=1)

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


async def _watch(board: Board, announcer: Announcer, clock: Clock) -> None:
    """Раз в секунду забирает сработавшие записи и объявляет их."""
    while True:
        now = clock.now()
        try:
            for entry in board.pop_due(now):
                await announcer.announce(phrases.fired_text(entry), entry.person)
        except Exception:
            # Сбой одного прохода (например, запись файла) не должен ронять коннектор.
            logger.exception("ошибка при проверке срабатываний")
        await clock.sleep_until(now + POLL)


def build_server(data_dir: Path, clock: Clock) -> MCPServer[Any]:
    """Собирает сервер таймеров над папкой данных `data_dir` и часами `clock`."""
    board = Board(Store(data_dir))
    announcer = Announcer()

    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncGenerator[dict[str, Any]]:
        now = clock.now()
        for entry in board.load(now):
            await announcer.announce(phrases.missed_text(entry, now.tzinfo), entry.person)
        async with anyio.create_task_group() as tg:
            tg.start_soon(_watch, board, announcer, clock)
            try:
                yield {}
            finally:
                tg.cancel_scope.cancel()

    server: MCPServer[Any] = MCPServer(
        "timers",
        instructions="Таймеры с именами и напоминания на время. Сработавшие объявляются вслух.",
        lifespan=lifespan,
        middleware=[announcer],
    )
    _add_tools(server, board, clock)
    return server


def _add_tools(server: MCPServer[Any], board: Board, clock: Clock) -> None:
    """Регистрирует инструменты. Они `async def`: синхронные SDK запускает в потоке, а так
    `Board` меняется только в цикле событий, как и в `_watch`, — без гонок."""

    @server.tool(
        structured_output=False,
        description="Поставить таймер на N минут, можно с именем. Пример: 20 минут, «картошка».",
    )
    async def timer_start(
        ctx: Context,
        minutes: Annotated[float, Field(description="Сколько минут, можно дробное: 0.5 — полминуты")],
        name: Annotated[str, Field(description="Имя таймера, например «картошка»; можно пусто")] = "",
    ) -> str:
        if not 0 < minutes <= MAX_MINUTES:
            raise ToolError("Таймер можно поставить от нескольких секунд до недели.")
        entry = board.start_timer(_person(ctx), minutes * 60, name, clock.now())
        return phrases.started_text(entry, minutes * 60)

    @server.tool(
        structured_output=False, description="Напомнить в заданное время. Пример: «18:30», «позвонить маме»."
    )
    async def reminder_at(
        ctx: Context,
        time: Annotated[str, Field(description="«ЧЧ:ММ» (сегодня, если прошло — завтра) или дата ISO")],
        text: Annotated[str, Field(description="О чём напомнить")],
    ) -> str:
        if not text.strip():
            raise ToolError("Не сказано, о чём напомнить.")
        now = clock.now()
        try:
            due = parse_reminder_time(time, now, clock.local)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return phrases.reminder_set_text(board.add_reminder(_person(ctx), due, text), now)

    @server.tool(structured_output=False, description="Какие таймеры и напоминания идут и сколько осталось.")
    async def timers(ctx: Context) -> str:
        return phrases.list_text(board.active(_person(ctx)), clock.now())

    @server.tool(
        structured_output=False, description="Отменить таймер или напоминание по имени; «все» — отменить все."
    )
    async def timer_cancel(
        ctx: Context,
        name: Annotated[str, Field(description="Имя таймера или текст напоминания; «все» — все")],
    ) -> str:
        removed = board.cancel(_person(ctx), name)
        return phrases.cancelled_text(name.strip(), removed, name.strip().casefold() == CANCEL_ALL)


def main() -> None:
    """Запуск коннектора по stdio; папка данных — из SMARTESP_CONNECTOR_DATA."""
    data = os.environ.get(DATA_ENV)
    if not data:
        raise SystemExit(f"timers-mcp: не задана переменная {DATA_ENV} — папка для данных коннектора.")
    data_dir = Path(data)
    data_dir.mkdir(parents=True, exist_ok=True)
    build_server(data_dir, SystemClock()).run("stdio")


if __name__ == "__main__":
    sys.exit(main())
