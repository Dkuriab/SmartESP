"""Сеть исполнителей: входной исполнитель передаёт задачу другим через инструмент delegate."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from smartesp.contracts import (
    ChatMessage,
    Executor,
    Handoff,
    ReplyPart,
    ToolBox,
    ToolCall,
    ToolObserver,
    ToolSpec,
    ToolUse,
    UsesModels,
    WarmsUp,
)

from .dialog import closing, flatten, question, speakable, with_task
from .guard import guarded
from .members import member_tools, warm
from .names import named_target
from .rules import DELEGATE_TOOL, Target
from .tool_loop import member_stream

_log = logging.getLogger(__name__)

MAX_DEPTH = 2  # передач в одном ходе: диспетчер → A → B
FAILURE_PHRASE = "{name} сейчас не отвечает."  # цель недоступна или ничего не сказала


@dataclass(frozen=True)
class Member:
    """Участник сети.

    executor — сам исполнитель; name — имя для журнала; targets — активные цели
    его связей; tools_ok — модель умеет инструменты (иначе ни инструмента, ни
    автопередачи по фразе); plain — тот же исполнитель с промптом без правила
    передачи: отвечает на глубине, где передавать уже нельзя (None — executor);
    tools — инструменты коннекторов (снимок ToolBox.specs() при сборке).
    """

    executor: Executor
    name: str
    targets: tuple[Target, ...]
    tools_ok: bool
    plain: Executor | None = None
    tools: tuple[ToolSpec, ...] = ()


@dataclass
class _Outcome:
    """Итог ответа одного участника: сказанный текст и выбранная передача."""

    text: list[str] = field(default_factory=list[str])
    called: bool = False  # был хоть один вызов delegate (верный или нет)
    handoff: Handoff | None = None
    guard: Literal["", "retried", "fallback"] = ""  # метка страховки с куска вызова delegate


class ExecutorNetwork:
    """Сеть исполнителей за договором Executor: для оркестратора — один исполнитель.

    Ход идёт так:
    - входной исполнитель отвечает; если у него есть цели и модель умеет
      инструменты — с инструментом delegate (плюс tools из run);
    - текст и чужие вызовы инструментов отдаются как есть;
    - первый верный вызов delegate (цель из его связей, непустая задача) —
      поток участника сразу закрывается (модель перестаёт генерировать, что
      было бы дальше — не читается), затем ReplyPart(handoff=…) и куски цели;
    - не было вызова, а весь ответ — короткая фраза с глаголом просьбы и именем
      одной цели (named_target) — та же передача с auto=True и задачей = вопрос
      человека (без пометок обработчиков и строки «Колонка: …»);
    - цель получает те же сообщения с дописанной задачей и свой инструмент,
      пока глубина передачи меньше max_depth; так же может передать дальше;
    - участник с tools_ok=False не получает никаких инструментов;
    - на глубине max_depth участник отвечает вариантом plain — без правила передачи;
    - ответ входного проверяет страховка честности (guard.py): ложное «сделала» без инструмента,
      пустой ответ, вызов текстом — один повторный прогон, затем честная фраза;
    - исключение цели — кусок «<Имя> сейчас не отвечает.» с failure;
      ExecutorError входного пробрасывается.
    """

    def __init__(
        self,
        entry: str,
        members: Mapping[str, Member],
        *,
        max_depth: int = MAX_DEPTH,
        unknown: frozenset[str] = frozenset(),
        toolbox: ToolBox | None = None,
        on_tool: ToolObserver | None = None,
    ) -> None:
        """entry — id входного исполнителя (должен быть в members); members — участники по id.

        unknown — модели, чьи возможности при сборке узнать не удалось (их tools_ok — False);
        toolbox — выполняет вызовы инструментов коннекторов (None — вызовы отдаются как есть);
        on_tool — получает начало и конец каждого вызова инструмента ящика.
        """
        if entry not in members:
            raise ValueError(f"Входного исполнителя «{entry}» нет среди участников сети")
        self.id = entry
        self._members = dict(members)
        self._max_depth = max_depth
        self._unknown = unknown
        self._toolbox = toolbox
        self._on_tool = on_tool

    @property
    def members(self) -> Mapping[str, Member]:
        """Участники сети по id (только для чтения)."""
        return MappingProxyType(self._members)

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт куски ответа сети; tools — дополнительные инструменты для входного."""
        parts = self._member_parts(self.id, messages, messages, tuple(tools), 0)
        async with closing(parts):
            async for part in parts:
                yield part

    async def _member_parts(
        self,
        member_id: str,
        base: list[ChatMessage],
        own: list[ChatMessage],
        extra_tools: tuple[ToolSpec, ...],
        depth: int,
    ) -> AsyncIterator[ReplyPart]:
        """Куски участника на глубине depth и, если он передал задачу, — куски цели.

        base — исходные сообщения хода; own — сообщения, которые получает участник.
        """
        member = self._members[member_id]
        offered = member.targets if member.tools_ok and depth < self._max_depth else ()
        tools = member_tools(member, offered, extra_tools)
        executor = member.executor
        if not offered:  # передать некому: ни правила, ни структуры вызовов delegate
            own = flatten(own, keep_tools=member.tools_ok)
            executor = member.plain or executor
        outcome = _Outcome()

        def start(messages: list[ChatMessage], seen: ToolObserver | None = None) -> AsyncIterator[ReplyPart]:
            observe = _both(seen, self._on_tool)
            return member_stream(
                member_id, self._toolbox, executor.run, messages, (tools, extra_tools), observe
            )

        names = frozenset(t.name for t in tools)  # у входного — страховка честности (guard.py)
        stream = guarded(member_id, start, own, names, bool(question(base))) if depth == 0 else start(own)
        parts = self._own_parts(member_id, stream, offered, outcome)
        async with closing(parts):
            async for part in parts:
                yield part
        handoff = outcome.handoff
        if handoff is None and offered and not outcome.called:
            handoff = self._auto_handoff(member_id, "".join(outcome.text), base, offered)
        if handoff is None:
            return
        yield ReplyPart(handoff=handoff, guard=outcome.guard)
        target_parts = self._target_parts(handoff, base, depth + 1)
        async with closing(target_parts):
            async for part in target_parts:
                yield part

    async def _own_parts(
        self,
        source: str,
        stream: AsyncIterator[ReplyPart],
        offered: tuple[Target, ...],
        outcome: _Outcome,
    ) -> AsyncIterator[ReplyPart]:
        """Собственные куски участника; вызовы delegate перехватываются в outcome.

        Первый верный вызов завершает поток участника.
        """
        async with closing(stream):
            async for part in stream:
                call = part.tool_call
                if call is not None and call.name == DELEGATE_TOOL:
                    outcome.called, outcome.guard = True, part.guard or outcome.guard
                    outcome.handoff = self._handoff(source, call, offered)
                    if outcome.handoff is not None:
                        return  # closing закрывает поток: остаток ответа не нужен
                    continue
                outcome.text.append(part.text)
                yield part

    def _handoff(self, source: str, call: ToolCall, offered: tuple[Target, ...]) -> Handoff | None:
        """Передача по вызову delegate или None (неизвестная цель, пустая задача)."""
        target_id, task = call.arguments.get("executor"), call.arguments.get("task")
        target = next((t for t in offered if t.id == target_id and t.id in self._members), None)
        if target is None:
            _log.warning("«%s» передаёт неизвестной цели %r — передачи нет", source, target_id)
            return None
        if not isinstance(task, str) or not task.strip():
            _log.warning("«%s» передаёт «%s» пустую задачу — передачи нет", source, target.id)
            return None
        _log.info("«%s» передаёт задачу «%s»: %s", source, target.id, task.strip())
        return Handoff(source, target.id, target.name, task.strip())

    def _auto_handoff(
        self, source: str, text: str, base: list[ChatMessage], offered: tuple[Target, ...]
    ) -> Handoff | None:
        """Передача по фразе без вызова («Сейчас спрошу большую модель.») или None."""
        target = named_target(text, offered)
        task = question(base)
        if target is None or target.id not in self._members or not task:
            return None
        _log.info("«%s» назвал «%s» без вызова delegate — передаём сами", source, target.id)
        return Handoff(source, target.id, target.name, task, auto=True)

    async def _target_parts(
        self, handoff: Handoff, base: list[ChatMessage], depth: int
    ) -> AsyncIterator[ReplyPart]:
        """Куски цели передачи; хотя бы один из них — с текстом для озвучки.

        Любое исключение цели (Exception) или ответ без текста (пусто, пробелы,
        одна метка стиля) — в конце фраза об ошибке с failure.
        """
        own = with_task(flatten(base, keep_tools=True), handoff.task)  # без инструментов уберёт _member_parts
        said: list[str] = []
        try:
            parts = self._member_parts(handoff.target, base, own, (), depth)
            async with closing(parts):
                async for part in parts:
                    said.append(part.text)
                    yield part
        except Exception:  # noqa: BLE001 — любой сбой цели озвучивается фразой, ход не падает
            _log.warning("Исполнитель «%s» недоступен", handoff.target, exc_info=True)
        else:
            if speakable("".join(said)):
                return
            _log.warning("Исполнитель «%s» ничего не сказал", handoff.target)
        yield ReplyPart(FAILURE_PHRASE.format(name=handoff.target_name), failure=True)

    async def warm_up(self) -> None:
        """Прогревает только входного исполнителя (остальных греет связка в фоне)."""
        entry = self._members[self.id].executor
        if isinstance(entry, WarmsUp):
            await entry.warm_up()

    async def warm_up_members(self, timeout_s: float) -> dict[str, str | None]:
        """Прогревает всех участников, кроме входного, одновременно; не бросает исключений.

        timeout_s — предел прогрева каждого, секунды. Возвращает {id: None, если
        прогрелся, иначе короткий текст ошибки} для участников, умеющих прогрев.
        """
        warmable = {
            member_id: member.executor
            for member_id, member in self._members.items()
            if member_id != self.id and isinstance(member.executor, WarmsUp)
        }
        results = await asyncio.gather(*(warm(i, e, timeout_s) for i, e in warmable.items()))
        return dict(zip(warmable, results, strict=True))

    def unknown_models(self) -> frozenset[str]:
        """Модели, чьи возможности при сборке были неизвестны: сеть стоит пересобрать, когда узнаем."""
        return self._unknown

    def models(self) -> frozenset[str]:
        """Объединение моделей всех участников."""
        names: set[str] = set()
        for member in self._members.values():
            if isinstance(member.executor, UsesModels):
                names |= member.executor.models()
        return frozenset(names)

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        """Выгружает названные модели через участников (каждую — один раз); не бросает исключений."""
        left = set(names)
        jobs: list[tuple[UsesModels, frozenset[str]]] = []
        for member in self._members.values():
            executor = member.executor
            if isinstance(executor, UsesModels) and (mine := executor.models() & left):
                left -= mine
                jobs.append((executor, mine))
        await asyncio.gather(*(executor.unload_models(mine, timeout_s) for executor, mine in jobs))


def _both(first: ToolObserver | None, second: ToolObserver | None) -> ToolObserver | None:
    """Наблюдатель, сообщающий о вызове обоим (None — никого)."""
    observers = [o for o in (first, second) if o is not None]
    if not observers:
        return None

    def observe(use: ToolUse) -> None:
        for observer in observers:
            observer(use)

    return observe
