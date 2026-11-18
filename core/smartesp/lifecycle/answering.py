"""Живые обработчики и исполнитель: подмена на лету, прогрев и выгрузка моделей."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import cast

from smartesp.contracts import Analyzer, Executor, ExecutorError, Unloads, WarmsUp

_log = logging.getLogger("smartesp")

Answering = tuple[Analyzer, Executor]  # обработчики и исполнитель: меняются вместе


class LiveAnswering:
    """Держит живую пару (обработчики, исполнитель) и все исполнители, чья модель может быть в памяти.

    Каждый собранный исполнитель, пока он не живой и не выгружен, числится «в стороне»:
    строится, греется, ждёт выгрузки или брошен отменённой правкой. unload_all при
    остановке выгружает живого и всех «в стороне», поэтому модель не остаётся в Ollama.
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
        self._analyze: Analyzer | None = None
        self._aside: list[Executor] = []  # не живые, но, возможно, загруженные
        self._closed = False

    async def warm_startup(self, part: Answering, timeout_s: float) -> None:
        """Греет пару старта (сбой — предупреждение) и ставит её, если правка не успела раньше.

        Если правку executors/stages применили, пока пара грелась, правка новее: пара
        старта освобождается, как старая.
        """
        self._set_aside(part[1])
        await warm_tolerant(part[1], timeout_s)
        if self.executor is None:
            self.use(part)
        else:
            await self.release(part)

    async def build(self, part: Answering, timeout_s: float) -> Answering:
        """Греет пару для правки настроек; не прогрелась — выгружает и пробрасывает ошибку."""
        executor = part[1]
        self._set_aside(executor)
        try:
            await warm_strict(executor, timeout_s)
        except Exception:
            await self._unload(executor)
            raise
        return part

    def use(self, part: object) -> object | None:
        """Ставит пару в оркестратор; возвращает прежнюю пару (теперь она «в стороне») или None."""
        analyze, executor = cast(Answering, part)
        old = None if self.executor is None else (self._analyze, self.executor)
        if self.executor is not None:
            self._set_aside(self.executor)
        self._forget(executor)
        self._analyze, self.executor = analyze, executor
        self._install(analyze, executor)
        return old

    async def release(self, part: object) -> None:
        """Выгружает модель исполнителя пары, если у живого другая; сначала ждёт идущие ходы.

        После остановки ничего не делает: исполнитель остаётся «в стороне» для unload_all.
        """
        _, old = cast(Answering, part)
        if self._closed:
            return
        if self._needs_unload(old):
            await self._wait_turns(self._turn_wait_s)
            if self._closed:
                return
            if self._needs_unload(old):  # живой мог смениться, пока ждали
                await self._unload(old)
        self._forget(old)

    async def unload_all(self) -> None:
        """Остановка: release больше не работает; выгружает модели живого и всех «в стороне».

        Каждая модель выгружается один раз, каждая — не дольше unload_s.
        """
        self._closed = True
        seen: set[str] = set()
        for executor in [self.executor, *self._aside]:
            if isinstance(executor, Unloads) and executor.model not in seen:
                seen.add(executor.model)
                await executor.unload(self._unload_s)
                _log.info("Остановка: модель %s выгружена", executor.model)

    def close(self) -> None:
        """Остановка началась: release больше ничего не ждёт и не выгружает."""
        self._closed = True

    def _needs_unload(self, executor: Executor) -> bool:
        live = self.executor
        same = isinstance(live, Unloads) and isinstance(executor, Unloads) and live.model == executor.model
        return isinstance(executor, Unloads) and not same

    async def _unload(self, executor: Executor) -> None:
        if isinstance(executor, Unloads):
            await executor.unload(self._unload_s)
        self._forget(executor)

    def _set_aside(self, executor: Executor) -> None:
        if all(e is not executor for e in self._aside):
            self._aside.append(executor)

    def _forget(self, executor: Executor) -> None:
        self._aside = [e for e in self._aside if e is not executor]


async def warm_strict(executor: Executor, timeout_s: float) -> None:
    """Прогрев для изменения настроек: ошибка или таймаут пробрасываются (изменение не применится)."""
    if isinstance(executor, WarmsUp):
        try:
            async with asyncio.timeout(timeout_s):
                await executor.warm_up()
        except TimeoutError:
            raise RuntimeError(f"модель не прогрелась за {timeout_s:g} с") from None


async def warm_tolerant(executor: Executor, timeout_s: float) -> None:
    """Прогрев при старте: сбой или таймаут — предупреждение, ядро всё равно работает."""
    if not isinstance(executor, WarmsUp):
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


def guarded[T](what: str, make: Callable[[], T]) -> T | None:
    """Вызывает make(); сбой — ошибка в журнале и None, а не исключение."""
    try:
        return make()
    except Exception:
        _log.error("%s не собран", what, exc_info=True)
        return None
