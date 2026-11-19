"""MCP-хаб: коннекторы как подпроцессы stdio, их инструменты — по договору ToolBox."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path

from smartesp.contracts import ConnectorState, ToolResult, ToolSpec

from .connector import Connector
from .messages import logger
from .naming import pick_name
from .specs import AnnounceHandler, ConnectorSpec

START_TIMEOUT_S = 10.0  # дольше коннектор при запуске не ждём
START_GRACE_S = 10.0  # запас на закрытие процесса, не уложившегося в предел запуска


class McpHub:
    """Запускает коннекторы, собирает их инструменты и вызывает их (реализует ToolBox).

    Имена инструментов — как у коннектора; при совпадении у второго (по порядку
    в настройках) или с `delegate` — префикс `<id>_`; символы вне [a-zA-Z0-9_-]
    заменяются на `_`, длинные имена обрезаются до 64 с хешем. Упавший коннектор перезапускается через
    restart_delays_s (последняя задержка повторяется); проработал минуту —
    счёт задержек сначала. После aclose хаб ничего не запускает.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        on_announce: AnnounceHandler | None = None,
        on_tools: Callable[[], None] | None = None,
        call_timeout_s: float = 15.0,
        restart_delays_s: tuple[float, ...] = (1.0, 5.0, 30.0, 300.0),
        start_timeout_s: float = START_TIMEOUT_S,
    ) -> None:
        """data_dir — папка данных ядра (коннектор получает <data_dir>/connectors/<id>);
        on_announce(text, person, connector_id) — коннектор просит сказать вслух;
        on_tools() — изменился список инструментов готовых коннекторов (specs()).
        """
        self._data_dir = data_dir
        self._on_announce = on_announce
        self._on_tools = on_tools
        self._call_timeout_s = call_timeout_s
        self._restart_delays_s = restart_delays_s
        self._start_timeout_s = start_timeout_s
        self._connectors: dict[str, Connector] = {}
        self._routes: dict[str, tuple[Connector, str]] = {}
        self._specs: list[ToolSpec] = []
        self._exposed: dict[str, tuple[str, ...]] = {}
        self._warned: set[str] = set()
        self._lock = asyncio.Lock()
        self._closed = False
        self._applying: set[asyncio.Task[None]] = set()  # правки apply_soon

    async def start(self, specs: Sequence[ConnectorSpec]) -> None:
        """Запускает коннекторы; ждёт каждого не дольше предела запуска. Упавший — failed, не исключение."""
        await self.apply(specs)

    async def apply(self, specs: Sequence[ConnectorSpec]) -> None:
        """Применяет новый список: изменённые перезапускает, убранные останавливает, новые запускает.

        Ждёт первой попытки запуска новых (не дольше предела запуска с запасом).
        """
        async with self._lock:
            if self._closed:
                return
            self._warned.clear()  # после правки настроек предупреждения о совпадениях — заново
            wanted = _unique(specs)
            old = self._connectors
            stale = [c for cid, c in old.items() if wanted.get(cid) != c.spec]
            await asyncio.gather(*(c.stop() for c in stale))
            fresh: list[Connector] = []
            connectors: dict[str, Connector] = {}
            for cid, spec in wanted.items():
                current = old.get(cid)
                if current is None or current.spec != spec:
                    current = self._make(spec)
                    fresh.append(current)
                connectors[cid] = current
            self._connectors = connectors
            self._rebuild()
            for connector in fresh:
                connector.launch()
        await self._wait_started(fresh)  # вне замка: остановка не ждёт чужого запуска

    def apply_soon(self, specs: Sequence[ConnectorSpec]) -> None:
        """Применяет список в фоне, не дожидаясь запуска; правки применяются по порядку вызовов."""
        if self._closed:
            return
        task = asyncio.create_task(self._apply_logged(list(specs)), name="mcp-hub-apply")
        self._applying.add(task)
        task.add_done_callback(self._applying.discard)

    def specs(self) -> list[ToolSpec]:
        """Описания инструментов готовых коннекторов (имена уникальны)."""
        return list(self._specs)

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        """Вызывает инструмент name; ошибка, таймаут, упавший коннектор — ToolResult(is_error=True)."""
        route = self._routes.get(name)
        if route is None:
            return ToolResult(f"Нет инструмента «{name}».", is_error=True)
        connector, tool = route
        return await connector.call(tool, arguments, person, self._call_timeout_s)

    def states(self) -> list[ConnectorState]:
        """Состояния коннекторов в порядке настроек (для интерфейса)."""
        return [
            ConnectorState(
                id=c.spec.id,
                name=c.spec.name,
                state=c.state,
                tools=self._exposed.get(c.spec.id, ()) if c.state == "ready" else (),
                error=c.error,
            )
            for c in self._connectors.values()
        ]

    async def aclose(self) -> None:
        """Останавливает все коннекторы и их процессы; фоновые правки отменяются. Повтор безопасен."""
        self._closed = True
        async with self._lock:
            connectors = list(self._connectors.values())
            self._connectors = {}
            self._rebuild()
            await asyncio.gather(*(c.stop() for c in connectors))
        applying = list(self._applying)
        for task in applying:
            task.cancel()
        await asyncio.gather(*applying, return_exceptions=True)

    async def _apply_logged(self, specs: list[ConnectorSpec]) -> None:
        try:
            await self.apply(specs)
        except Exception:
            logger.exception("Коннекторы: настройки не применены")

    def _make(self, spec: ConnectorSpec) -> Connector:
        return Connector(
            spec,
            self._data_dir,
            on_announce=self._on_announce,
            on_change=self._rebuild,
            start_timeout_s=self._start_timeout_s,
            restart_delays_s=self._restart_delays_s,
        )

    async def _wait_started(self, connectors: list[Connector]) -> None:
        """Ждёт первой попытки запуска каждого (параллельно), но не дольше предела с запасом."""
        if not connectors:
            return
        waits = [asyncio.create_task(c.wait_settled()) for c in connectors]
        try:
            await asyncio.wait(waits, timeout=self._start_timeout_s + START_GRACE_S)
        finally:
            for task in waits:
                task.cancel()

    def _rebuild(self) -> None:
        """Пересобирает таблицу имён инструментов по всем коннекторам (в порядке настроек)."""
        routes: dict[str, tuple[Connector, str]] = {}
        specs: list[ToolSpec] = []
        exposed: dict[str, tuple[str, ...]] = {}
        for connector in self._connectors.values():
            names: list[str] = []
            for tool in connector.tools:
                name = self._free_name(routes, connector.spec.id, tool.name)
                if name is None:
                    continue
                routes[name] = (connector, tool.name)
                names.append(name)
                if connector.state == "ready":
                    specs.append(ToolSpec(name, tool.description or "", dict(tool.input_schema)))
            exposed[connector.spec.id] = tuple(names)
        changed = specs != self._specs
        self._routes, self._specs, self._exposed = routes, specs, exposed
        if changed and self._on_tools is not None:
            try:
                self._on_tools()
            except Exception:
                logger.exception("Коннекторы: обработчик смены инструментов упал")

    def _free_name(self, routes: dict[str, tuple[Connector, str]], cid: str, tool: str) -> str | None:
        """Имя инструмента для модели: своё или с префиксом `<id>_` (см. pick_name); None — не нашлось."""
        name = pick_name(routes, cid, tool)
        if name == tool:
            return name
        key = f"{cid}/{tool}"
        if key not in self._warned:
            self._warned.add(key)
            if name is None:
                logger.warning("Инструмент %s коннектора %s пропущен: имя занято", tool, cid)
            else:
                logger.warning("Инструмент %s коннектора %s назван %s", tool, cid, name)
        return name


def _unique(specs: Sequence[ConnectorSpec]) -> dict[str, ConnectorSpec]:
    """Коннекторы по id в порядке настроек; повтор id — берётся первый, в журнал предупреждение."""
    result: dict[str, ConnectorSpec] = {}
    for spec in specs:
        if spec.id in result:
            logger.warning("Коннектор %s указан дважды; второй пропущен", spec.id)
            continue
        result[spec.id] = spec
    return result
