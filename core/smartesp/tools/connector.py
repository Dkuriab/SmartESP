"""Один коннектор: подпроцесс MCP (stdio), его сессия, перезапуск после падения."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Protocol, TextIO, cast

import anyio
from anyio.streams.memory import MemoryObjectSendStream
from mcp import ClientSession, stdio_client, types
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage

from smartesp.contracts import TaskBoard, ToolResult

from .messages import handle_log, logger, tool_result
from .process import kill_group, launch_params
from .specs import AnnounceHandler, ConnectorSpec, StateName

DATA_ENV = "SMARTESP_CONNECTOR_DATA"  # папка данных коннектора
STABLE_S = 60.0  # проработал дольше — счёт падений для задержек начинается заново
STOP_TIMEOUT_S = 10.0  # запасной предел остановки: SDK закрывает процесс за ~6,5 с (stdin, SIGTERM, SIGKILL)
KILL_WAIT_S = 1.0  # после SIGKILL ждём конца задачи не дольше
CALL_GRACE_S = 2.0  # запас сверх предела вызова на случай, если не сработал предел SDK

Incoming = SessionMessage | Exception


class _Source(Protocol):
    """Поток входящих сообщений транспорта."""

    async def receive(self) -> Incoming: ...


class Connector:
    """Запускает коннектор, держит его сессию и перезапускает после падения.

    Вся жизнь подпроцесса — в одной задаче (`_main`); остановка — отменой её
    области anyio, так что SDK успевает закрыть процесс (stdin, SIGTERM, SIGKILL).
    """

    def __init__(
        self,
        spec: ConnectorSpec,
        data_dir: Path,
        *,
        on_announce: AnnounceHandler | None,
        tasks: TaskBoard | None = None,
        on_change: Callable[[], None],
        start_timeout_s: float,
        restart_delays_s: tuple[float, ...],
        core_env: dict[str, str] | None = None,
    ) -> None:
        self.spec = spec
        self._core_env = dict(core_env or {}) if spec.core_api else {}  # адрес и токен API ядра
        self.state: StateName = "starting" if spec.enabled else "disabled"
        self.error = ""
        self.tools: tuple[types.Tool, ...] = ()  # последний полученный список (держится и при падении)
        self._data_dir = data_dir / "connectors" / spec.id
        self._pid_file = data_dir / "run" / "connectors" / f"{spec.id}.pid"
        self._on_announce = on_announce
        self._tasks = tasks
        self._on_change = on_change
        self._start_timeout_s = start_timeout_s
        self._delays = restart_delays_s or (1.0,)
        self._session: ClientSession | None = None
        self._settled = asyncio.Event()  # первая попытка запуска закончилась (готов или упал)
        self._scope = anyio.CancelScope()
        self._task: asyncio.Task[None] | None = None

    def launch(self) -> None:
        """Запускает коннектор в фоне (выключенный — не запускает)."""
        if not self.spec.enabled:
            self._settled.set()
            return
        self._task = asyncio.create_task(self._main(), name=f"connector-{self.spec.id}")

    async def wait_settled(self) -> None:
        """Ждёт конца первой попытки запуска: готов, упал или выключен."""
        await self._settled.wait()

    async def stop(self, timeout_s: float = STOP_TIMEOUT_S) -> None:
        """Останавливает коннектор и его процесс; не бросает исключений.

        Не закрылся за timeout_s (SDK: stdin, SIGTERM, SIGKILL) — группа процессов
        коннектора получает SIGKILL сразу; итого не дольше timeout_s + KILL_WAIT_S.
        """
        self._scope.cancel()
        task = self._task
        if task is not None:
            done, _ = await asyncio.wait({task}, timeout=timeout_s)
            if not done:
                kill_group(self._pid_file, self.spec.id)
                done, _ = await asyncio.wait({task}, timeout=KILL_WAIT_S)
            if not done:
                logger.error("Коннектор %s не остановился", self.spec.id)
                task.cancel()
        self._session = None

    async def call(
        self, tool: str, arguments: dict[str, object], context: dict[str, str], timeout: float
    ) -> ToolResult:
        """Вызывает инструмент коннектора; context — `_meta` вызова (person, device); ошибки и таймаут —
        ToolResult(is_error=True)."""
        session = self._session
        if session is None or self.state != "ready":
            return ToolResult(f"Коннектор «{self.spec.name}» недоступен.", is_error=True)
        meta: types.RequestParamsMeta | None = (
            cast(types.RequestParamsMeta, dict(context)) if context else None
        )
        try:
            async with asyncio.timeout(timeout + CALL_GRACE_S):
                result = await session.call_tool(
                    tool, dict(arguments), read_timeout_seconds=timeout, meta=meta
                )
        except TimeoutError:
            return self._not_responding()
        except MCPError as exc:
            return self._mcp_error(tool, exc)
        except Exception:
            logger.exception("Коннектор %s: вызов %s не удался", self.spec.id, tool)
            return ToolResult(f"Коннектор «{self.spec.name}»: вызов не удался.", is_error=True)
        return tool_result(result)

    def _not_responding(self) -> ToolResult:
        return ToolResult(f"Коннектор «{self.spec.name}» не отвечает.", is_error=True)

    def _mcp_error(self, tool: str, exc: MCPError) -> ToolResult:
        """Текст ошибки протокола для модели."""
        if exc.code == types.REQUEST_TIMEOUT:
            return self._not_responding()
        logger.warning("Коннектор %s: вызов %s — ошибка %s", self.spec.id, tool, exc.message)
        if exc.code == types.CONNECTION_CLOSED:
            return ToolResult(f"Коннектор «{self.spec.name}» недоступен.", is_error=True)
        return ToolResult(f"Коннектор «{self.spec.name}»: {exc.message}", is_error=True)

    async def _main(self) -> None:
        """Задача коннектора: попытки запуска и перезапуски до остановки."""
        try:
            with self._scope:
                await self._supervise()
        except Exception:
            logger.exception("Коннектор %s: сбой хаба", self.spec.id)
            self._set("failed", "Внутренняя ошибка хаба.")
        finally:
            self._session = None
            self._settled.set()
            self._pid_file.unlink(missing_ok=True)

    async def _supervise(self) -> None:
        """Запускает сессию снова и снова; между падениями ждёт по restart_delays_s."""
        failures = 0
        while True:
            began = time.monotonic()
            error = await self._run_once()
            self._fail(error)
            if time.monotonic() - began >= STABLE_S:
                failures = 0
            delay = self._delays[min(failures, len(self._delays) - 1)]
            failures += 1
            logger.warning("Коннектор %s упал (%s); перезапуск через %g с", self.spec.id, error, delay)
            await anyio.sleep(delay)
            self._set("starting", self.error)

    async def _run_once(self) -> str:
        """Одна жизнь подпроцесса: запуск, готовность, ожидание конца. Возвращает текст ошибки."""
        try:
            async with AsyncExitStack() as stack:
                session, lost = await self._open(stack)
                tools = await self._handshake(session)
                if tools is None:
                    error = f"Не запустился за {self._start_timeout_s:g} с."
                    self._fail(error)  # сразу: закрытие процесса ещё займёт время
                    return error
                self._ready(session, tools)
                await lost.wait()
                self._fail("Коннектор завершился.")
                return "Коннектор завершился."
        except Exception as exc:
            return _describe(exc)

    async def _handshake(self, session: ClientSession) -> tuple[types.Tool, ...] | None:
        """Рукопожатие и список инструментов в пределах запуска; не уложился — None."""
        with anyio.move_on_after(self._start_timeout_s):
            # initialize() — рукопожатие протокола 2025-11-25 (legacy): в нём коннектор
            # вправе слать уведомления журнала вне вызова (объявления таймеров)
            await session.initialize()
            return await _list_tools(session)
        return None

    async def _open(self, stack: AsyncExitStack) -> tuple[ClientSession, anyio.Event]:
        """Запускает подпроцесс и открывает сессию; lost срабатывает, когда процесс закрыл stdout."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        params = launch_params(self.spec.command, self.spec.args, self._env(), self._pid_file)
        read, write = await stack.enter_async_context(stdio_client(params, errlog=_errlog()))
        send, receive = anyio.create_memory_object_stream[Incoming](0)
        stack.push_async_callback(receive.aclose)
        lost = anyio.Event()
        pumps = await stack.enter_async_context(anyio.create_task_group())
        stack.callback(pumps.cancel_scope.cancel)  # насос стоит на чтении — отменить до выхода группы
        pumps.start_soon(_pump, read, send, lost)
        session = ClientSession(receive, write, logging_callback=self._log)
        await stack.enter_async_context(session)
        stack.callback(self._forget, session)
        return session, lost

    def _env(self) -> dict[str, str]:
        """Окружение подпроцесса: окружение ядра + env из настроек + папка данных."""
        return {**os.environ, **self.spec.env, **self._core_env, DATA_ENV: str(self._data_dir)}

    async def _log(self, params: types.LoggingMessageNotificationParams) -> None:
        handle_log(params, self.spec.id, self._on_announce, self._tasks)

    def _ready(self, session: ClientSession, tools: tuple[types.Tool, ...]) -> None:
        self._session = session
        self.tools = tools
        logger.info("Коннектор %s готов: %s", self.spec.id, ", ".join(t.name for t in tools))
        self._set("ready", "")

    def _fail(self, error: str) -> None:
        self._session = None
        if self.state != "failed":
            self._set("failed", error)

    def _forget(self, session: ClientSession) -> None:
        if self._session is session:
            self._session = None

    def _set(self, state: StateName, error: str) -> None:
        self.state, self.error = state, error
        if state in ("ready", "failed"):
            self._settled.set()
        self._on_change()


async def _list_tools(session: ClientSession) -> tuple[types.Tool, ...]:
    """Все инструменты сервера (с учётом постраничной выдачи)."""
    tools: list[types.Tool] = []
    cursor: str | None = None
    while True:
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        page = await session.list_tools(params=params)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tuple(tools)


async def _pump(source: _Source, sink: MemoryObjectSendStream[Incoming], lost: anyio.Event) -> None:
    """Передаёт сообщения транспорта в сессию; конец потока — процесс завершился."""
    try:
        async with sink:
            while True:
                await sink.send(await source.receive())
    except (anyio.EndOfStream, anyio.ClosedResourceError, anyio.BrokenResourceError):
        pass
    finally:
        lost.set()


def _describe(exc: BaseException) -> str:
    """Короткий текст ошибки запуска (из группы исключений — первое)."""
    while isinstance(exc, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], exc)
        exc = group.exceptions[0]
    if isinstance(exc, MCPError) and exc.code == types.CONNECTION_CLOSED:
        return "Процесс коннектора завершился."
    if isinstance(exc, FileNotFoundError):
        return "Не удалось запустить: команда не найдена."
    if isinstance(exc, OSError):
        return f"Не удалось запустить: {exc.strerror or exc}."
    return f"{type(exc).__name__}: {exc}"


def _errlog() -> TextIO:
    """Куда пишет stderr коннектора: stderr ядра (если у него есть файловый дескриптор)."""
    try:
        sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        return sys.__stderr__ or sys.stderr
    return sys.stderr
