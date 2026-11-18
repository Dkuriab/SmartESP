"""Живые обработчики и исполнитель: подмена на лету, прогрев и выгрузка модели."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, cast, runtime_checkable

from smartesp.contracts import Analyzer, Executor, ExecutorError

_log = logging.getLogger("smartesp")

Answering = tuple[Analyzer, Executor]  # обработчики и исполнитель: меняются вместе


@runtime_checkable
class _WarmsUp(Protocol):
    async def warm_up(self) -> None: ...


@runtime_checkable
class _Unloads(Protocol):
    model: str

    async def unload(self, timeout_s: float = ...) -> None: ...


class LiveAnswering:
    """Держит живую пару (обработчики, исполнитель) и правила её смены.

    use ставит пару в оркестратор; release выгружает модель старого исполнителя,
    если живой работает на другой модели, — но сначала ждёт идущие ходы.
    """

    def __init__(
        self,
        install: Callable[[Analyzer, Executor], None],
        wait_turns: Callable[[float], Awaitable[None]],
        *,
        turn_wait_s: float,
        unload_s: float,
    ) -> None:
        """install(обработчики, исполнитель) — подмена в оркестраторе; wait_turns(с) — ждать ходы."""
        self._install = install
        self._wait_turns = wait_turns
        self._turn_wait_s = turn_wait_s
        self._unload_s = unload_s
        self.executor: Executor | None = None
        self.starting: Executor | None = None  # исполнитель, который греется при старте
        self._analyze: Analyzer | None = None

    def use(self, part: object) -> object | None:
        """Ставит пару (обработчики, исполнитель); возвращает прежнюю пару или None."""
        analyze, executor = cast(Answering, part)
        old = None if self.executor is None else (self._analyze, self.executor)
        self._analyze, self.executor = analyze, executor
        self._install(analyze, executor)
        return old

    async def release(self, part: object) -> None:
        """Выгружает модель исполнителя пары, если она не у живого; сначала ждёт идущие ходы."""
        _, old = cast(Answering, part)
        if not isinstance(old, _Unloads):
            return
        if isinstance(self.executor, _Unloads) and self.executor.model == old.model:
            return
        await self._wait_turns(self._turn_wait_s)
        await old.unload(self._unload_s)

    async def unload_live(self) -> None:
        """Выгружает модели живого и ещё греющегося исполнителя (при остановке)."""
        for executor in (self.executor, self.starting):
            if isinstance(executor, _Unloads):
                await executor.unload(self._unload_s)
                _log.info("Остановка: модель %s выгружена", executor.model)


async def warm_strict(executor: Executor, timeout_s: float) -> None:
    """Прогрев для изменения настроек: ошибка или таймаут пробрасываются (изменение не применится)."""
    if isinstance(executor, _WarmsUp):
        try:
            async with asyncio.timeout(timeout_s):
                await executor.warm_up()
        except TimeoutError:
            raise RuntimeError(f"модель не прогрелась за {timeout_s:g} с") from None


async def warm_tolerant(executor: Executor, timeout_s: float) -> None:
    """Прогрев при старте: сбой или таймаут — предупреждение, ядро всё равно работает."""
    if not isinstance(executor, _WarmsUp):
        return
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout_s):
            await executor.warm_up()
        _log.info("Исполнитель прогрет за %.1f с", time.monotonic() - started)
    except ExecutorError as error:
        _log.warning("Ollama недоступна: %s. Ходы будут заканчиваться сигналом ошибки.", error)
    except TimeoutError:
        _log.warning("Исполнитель не прогрелся за %g с; работаю без прогрева.", timeout_s)


async def timed(what: str, work: Awaitable[object]) -> None:
    """Ждёт прогрев части и пишет в журнал время; сбой — ошибка в журнале, не исключение."""
    started = time.monotonic()
    try:
        await work
        _log.info("%s прогрет за %.1f с", what, time.monotonic() - started)
    except Exception:
        _log.error("%s не прогрелся", what, exc_info=True)
