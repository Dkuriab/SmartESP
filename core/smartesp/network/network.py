"""Сеть исполнителей: входной исполнитель передаёт задачу другим через инструмент delegate."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from smartesp.contracts import (
    ChatMessage,
    Executor,
    ExecutorError,
    Handoff,
    ReplyPart,
    ToolCall,
    ToolSpec,
    UsesModels,
    WarmsUp,
)

from .names import named_target
from .rules import DELEGATE_TOOL, Target, delegate_tool

_log = logging.getLogger(__name__)

MAX_DEPTH = 2  # передач в одном ходе: диспетчер → A → B
TASK_PREFIX = "\n\nЗадача от диспетчера: "  # дописывается к последнему сообщению user у цели
FAILURE_PHRASE = "Не получилось спросить {name}."  # цель недоступна


@dataclass(frozen=True)
class Member:
    """Участник сети.

    executor — сам исполнитель; name — имя для журнала; targets — активные цели
    его связей; tools_ok — модель умеет инструменты (иначе ни инструмента, ни
    автопередачи по фразе).
    """

    executor: Executor
    name: str
    targets: tuple[Target, ...]
    tools_ok: bool


@dataclass
class _Outcome:
    """Итог ответа одного участника: сказанный текст и выбранная передача."""

    text: list[str] = field(default_factory=list[str])
    called: bool = False  # был хоть один вызов delegate (верный или нет)
    handoff: Handoff | None = None


@asynccontextmanager
async def _closing(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[AsyncIterator[ReplyPart]]:
    """Как contextlib.aclosing, но для любого AsyncIterator: закрывает его, если это генератор."""
    try:
        yield parts
    finally:
        if isinstance(parts, AsyncGenerator):
            await parts.aclose()


def _with_task(messages: list[ChatMessage], task: str) -> list[ChatMessage]:
    """Копия сообщений, где к последнему сообщению user дописана задача от диспетчера."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            last = messages[index]
            changed = ChatMessage("user", last.content + TASK_PREFIX + task)
            return [*messages[:index], changed, *messages[index + 1 :]]
    return [*messages, ChatMessage("user", TASK_PREFIX.lstrip() + task)]


def _last_user_text(messages: list[ChatMessage]) -> str:
    """Текст последнего сообщения user (пусто, если такого нет)."""
    return next((m.content for m in reversed(messages) if m.role == "user"), "")


class ExecutorNetwork:
    """Сеть исполнителей за договором Executor: для оркестратора — один исполнитель.

    Ход идёт так:
    - входной исполнитель отвечает; если у него есть цели и модель умеет
      инструменты — с инструментом delegate (плюс tools из run);
    - текст и чужие вызовы инструментов отдаются как есть;
    - первый верный вызов delegate (цель из его связей, непустая задача) —
      остаток ответа дочитывается и отбрасывается (второй вызов — в журнал),
      затем ReplyPart(handoff=…) и куски цели;
    - не было вызова, а весь ответ — короткая фраза с именем одной цели
      (named_target) — та же передача с auto=True и задачей = вопрос человека;
    - цель получает те же сообщения с дописанной задачей и свой инструмент,
      пока глубина передачи меньше max_depth; так же может передать дальше;
    - ExecutorError цели — кусок «Не получилось спросить <имя>.» с failure;
      ExecutorError входного пробрасывается.
    """

    def __init__(self, entry: str, members: Mapping[str, Member], *, max_depth: int = MAX_DEPTH) -> None:
        """entry — id входного исполнителя (должен быть в members); members — участники по id."""
        if entry not in members:
            raise ValueError(f"Входного исполнителя «{entry}» нет среди участников сети")
        self.id = entry
        self._members = dict(members)
        self._max_depth = max_depth

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт куски ответа сети; tools — дополнительные инструменты для входного."""
        parts = self._member_parts(self.id, messages, messages, tuple(tools), 0)
        async with _closing(parts):
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
        tools = (*extra_tools, delegate_tool(offered)) if offered else extra_tools
        outcome = _Outcome()
        parts = self._own_parts(member_id, member.executor.run(own, tools), offered, outcome)
        async with _closing(parts):
            async for part in parts:
                yield part
        handoff = outcome.handoff
        if handoff is None and offered and not outcome.called:
            handoff = self._auto_handoff(member_id, "".join(outcome.text), base, offered)
        if handoff is None:
            return
        yield ReplyPart(handoff=handoff)
        target_parts = self._target_parts(handoff, base, depth + 1)
        async with _closing(target_parts):
            async for part in target_parts:
                yield part

    async def _own_parts(
        self,
        source: str,
        stream: AsyncIterator[ReplyPart],
        offered: tuple[Target, ...],
        outcome: _Outcome,
    ) -> AsyncIterator[ReplyPart]:
        """Собственные куски участника; вызовы delegate перехватываются в outcome."""
        async with _closing(stream):
            async for part in stream:
                if outcome.handoff is not None:
                    _ignore_after_handoff(source, part)
                    continue
                call = part.tool_call
                if call is not None and call.name == DELEGATE_TOOL:
                    outcome.called = True
                    outcome.handoff = self._handoff(source, call, offered)
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
        task = _last_user_text(base).strip()
        if target is None or target.id not in self._members or not task:
            return None
        _log.info("«%s» назвал «%s» без вызова delegate — передаём сами", source, target.id)
        return Handoff(source, target.id, target.name, task, auto=True)

    async def _target_parts(
        self, handoff: Handoff, base: list[ChatMessage], depth: int
    ) -> AsyncIterator[ReplyPart]:
        """Куски цели передачи; её ExecutorError — фраза об ошибке с failure."""
        own = _with_task(base, handoff.task)
        try:
            parts = self._member_parts(handoff.target, base, own, (), depth)
            async with _closing(parts):
                async for part in parts:
                    yield part
        except ExecutorError as exc:
            _log.warning("Исполнитель «%s» недоступен: %s", handoff.target, exc)
            yield ReplyPart(FAILURE_PHRASE.format(name=handoff.target_name), failure=True)

    async def warm_up(self) -> None:
        """Прогревает только входного исполнителя (остальных греет связка в фоне)."""
        entry = self._members[self.id].executor
        if isinstance(entry, WarmsUp):
            await entry.warm_up()

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


def _ignore_after_handoff(source: str, part: ReplyPart) -> None:
    """Куски после выбранной передачи не звучат; второй delegate — предупреждение в журнал."""
    call = part.tool_call
    if call is not None and call.name == DELEGATE_TOOL:
        _log.warning("«%s»: второй вызов delegate в одном ответе проигнорирован: %r", source, call.arguments)
    elif part.text:
        _log.debug("«%s»: текст после вызова delegate отброшен: %r", source, part.text)
