"""Живые обработчики и исполнитель (сеть): подмена на лету, прогрев и выгрузка наборов моделей."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, cast, runtime_checkable

from smartesp.contracts import Analyzer, Executor, ExecutorError, UsesModels, WarmsUp

_log = logging.getLogger("smartesp")

Answering = tuple[Analyzer, Executor]  # обработчики и исполнитель: меняются вместе


@runtime_checkable
class _WarmsMembers(Protocol):
    """Сеть исполнителей: прогрев участников, кроме входного (не бросает исключений)."""

    async def warm_up_members(self, timeout_s: float) -> dict[str, str | None]: ...


def _models(executor: Executor | None) -> frozenset[str]:
    """Модели, которые держит исполнитель (не UsesModels — никаких)."""
    return executor.models() if isinstance(executor, UsesModels) else frozenset()


class LiveAnswering:
    """Держит живую пару (обработчики, исполнитель) и все исполнители, чьи модели могут быть в памяти.

    Исполнитель — обычно сеть: у неё набор моделей. Каждый собранный исполнитель,
    пока он не живой и не выгружен, числится «в стороне»: строится, греется, ждёт
    выгрузки или брошен отменённой правкой. unload_all при остановке выгружает
    модели живого и всех «в стороне», поэтому модели не остаются в Ollama.

    После подмены участники сети, кроме входного, греются в фоне: это не задерживает
    ни старт, ни правку; итог — в members_warmth. Пара, собранная без прогрева
    (build(warm=False) — пересборка под инструменты с теми же моделями), при подмене
    участников не греет: выгруженная владельцем модель так и остаётся выгруженной.
    """

    def __init__(
        self,
        install: Callable[[Analyzer, Executor], None],
        wait_turns: Callable[[float], Awaitable[None]],
        *,
        turn_wait_s: float,
        unload_s: float,
        member_warm_s: float = 120.0,
    ) -> None:
        """install(обработчики, исполнитель) — подмена в оркестраторе; wait_turns(с) — ждать ходы.

        member_warm_s — предел фонового прогрева каждого участника, секунды.
        """
        self._install = install
        self._wait_turns = wait_turns
        self._turn_wait_s = turn_wait_s
        self._unload_s = unload_s
        self._member_warm_s = member_warm_s
        self.executor: Executor | None = None
        self._analyze: Analyzer | None = None
        self._aside: list[Executor] = []  # не живые, но, возможно, загруженные
        self._releasing: list[Executor] = []  # ждут в release конца идущих ходов: их модели заняты
        self._cold: list[Executor] = []  # собраны без прогрева: подмена их не греет
        self._closed = False
        self._members_warming: asyncio.Task[None] | None = None
        # итог фонового прогрева живой сети: {id: None — прогрет, иначе текст ошибки}
        self.members_warmth: dict[str, str | None] = {}

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

    async def build(self, part: Answering, timeout_s: float, *, warm: bool = True) -> Answering:
        """Греет пару для правки настроек (у сети — только входного); не прогрелась — ошибка.

        Выгружаются только те модели не прогревшегося исполнителя, которых нет ни
        у живого, ни у ждущих в release: иначе выгрузка оборвала бы их ходы.
        warm=False (пересборка по тем же настройкам) — не греть ни сейчас, ни при подмене,
        если у пары те же модели, что у живой; иначе новые модели греются как обычно.
        """
        executor = part[1]
        self._set_aside(executor)
        if not warm and self.executor is not None and _models(executor) == _models(self.executor):
            self._cold.append(executor)
            return part
        try:
            await warm_strict(executor, timeout_s)
        except Exception:
            busy = frozenset[str]().union(*(_models(e) for e in self._releasing))
            await self._unload(executor, self._leaving(executor) - busy)
            raise
        return part

    async def rebuild(self, build: Callable[[], Awaitable[Answering]]) -> bool:
        """Пересборка живой пары тем же путём, что правка: build() (с прогревом) → use → release.

        Если, пока пара собиралась, живую сменила правка или началась остановка,
        новая пара освобождается, а живая остаётся. True — пара подменена.
        Ошибка build пробрасывается.
        """
        current = self.executor
        part = await build()
        if self._closed or self.executor is not current:
            await self.release(part)
            return False
        old = self.use(part)
        if old is not None:
            await self.release(old)
        return True

    def use(self, part: object) -> object | None:
        """Ставит пару в оркестратор и начинает фоновый прогрев участников.

        Возвращает прежнюю пару (теперь она «в стороне») или None.
        """
        analyze, executor = cast(Answering, part)
        old = None if self.executor is None else (self._analyze, self.executor)
        cold = any(e is executor for e in self._cold)
        if self.executor is not None:
            self._set_aside(self.executor)
        self._forget(executor)
        self._analyze, self.executor = analyze, executor
        self._install(analyze, executor)
        if not cold:  # те же модели: идущий прогрев и его итог остаются в силе
            self._warm_members(executor)
        return old

    async def release(self, part: object) -> None:
        """Выгружает модели пары, которых нет у живого; сначала ждёт идущие ходы.

        После ожидания набор проверяется снова: живой мог смениться. После
        остановки ничего не делает: исполнитель остаётся «в стороне» для unload_all.
        """
        _, old = cast(Answering, part)
        if self._closed:
            return
        if self._leaving(old):
            self._releasing.append(old)
            try:
                await self._wait_turns(self._turn_wait_s)
            finally:
                self._releasing = [e for e in self._releasing if e is not old]
            if self._closed:
                return
            await self._unload(old, self._leaving(old))
        self._forget(old)

    async def unload_all(self) -> None:
        """Остановка: release больше не работает; выгружает модели живого и всех «в стороне».

        Фоновый прогрев участников отменяется. Каждая модель выгружается один раз;
        исполнители — одновременно, каждая модель — не дольше unload_s. Сбой
        выгрузки только пишется в журнал.
        """
        self.close()
        if self._members_warming is not None:
            await asyncio.gather(self._members_warming, return_exceptions=True)
        claimed: set[str] = set()
        jobs: list[tuple[UsesModels, frozenset[str]]] = []
        for executor in [self.executor, *self._aside]:
            if isinstance(executor, UsesModels) and (mine := executor.models() - claimed):
                claimed |= mine
                jobs.append((executor, mine))
        await asyncio.gather(*(self._unload_on_stop(e, names) for e, names in jobs))

    async def _unload_on_stop(self, executor: UsesModels, names: frozenset[str]) -> None:
        listed = ", ".join(sorted(names))
        try:
            await executor.unload_models(names, self._unload_s)
        except Exception:
            _log.warning("Остановка: модели %s не выгружены", listed, exc_info=True)
            return
        _log.info("Остановка: модели %s выгружены", listed)

    def close(self) -> None:
        """Остановка началась: release больше ничего не ждёт и не выгружает, прогрев отменён."""
        self._closed = True
        if self._members_warming is not None:
            self._members_warming.cancel()

    def _warm_members(self, executor: Executor) -> None:
        """Отменяет прогрев прежней сети и, если можно, начинает прогрев участников новой."""
        if self._members_warming is not None:
            self._members_warming.cancel()
            self._members_warming = None
        self.members_warmth = {}
        if not self._closed and isinstance(executor, _WarmsMembers):
            warming = self._warm_members_of(executor)
            self._members_warming = asyncio.create_task(warming, name="members-warm-up")

    async def _warm_members_of(self, executor: _WarmsMembers) -> None:
        started = time.monotonic()
        try:
            result = await executor.warm_up_members(self._member_warm_s)
        except Exception:
            _log.warning("Фоновый прогрев исполнителей упал", exc_info=True)
            return
        self.members_warmth = result
        if result:
            ready = [member_id for member_id, error in result.items() if error is None]
            _log.info("Исполнители прогреты за %.1f с: %s", time.monotonic() - started, ready)

    def _leaving(self, executor: Executor) -> frozenset[str]:
        """Модели исполнителя, которых нет у живого."""
        return _models(executor) - _models(self.executor)

    async def _unload(self, executor: Executor, names: frozenset[str]) -> None:
        if names and isinstance(executor, UsesModels):
            await executor.unload_models(names, self._unload_s)
        self._forget(executor)

    def _set_aside(self, executor: Executor) -> None:
        if all(e is not executor for e in self._aside):
            self._aside.append(executor)

    def _forget(self, executor: Executor) -> None:
        self._aside = [e for e in self._aside if e is not executor]
        self._cold = [e for e in self._cold if e is not executor]


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
        _log.warning("Исполнитель не прогрелся: %s. Ходы будут заканчиваться сигналом ошибки.", error)
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


async def guarded[T](what: str, work: Awaitable[T]) -> T | None:
    """Ждёт work; сбой — ошибка в журнале и None, а не исключение."""
    try:
        return await work
    except Exception:
        _log.error("%s не собран", what, exc_info=True)
        return None
