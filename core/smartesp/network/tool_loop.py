"""Вызов инструментов коннекторов: модель вызвала → ящик выполнил → результат в диалог → модель продолжает."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from smartesp.contracts import (
    DELEGATE_TOOL,
    ChatMessage,
    ReplyPart,
    ToolBox,
    ToolCall,
    ToolObserver,
    ToolResult,
    ToolSpec,
    ToolUse,
)

from .dialog import closing

_log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 4  # вызовов инструментов на один ответ участника
TOOL_FAILURE_PHRASE = "Не получилось выполнить действие."  # вызовов больше предела
UNKNOWN_TOOL = "Нет такого инструмента: {name}"  # модель вызвала то, чего ей не давали
TOOL_CRASHED = "Инструмент {name} не сработал."  # ящик бросил исключение вопреки договору
TOOL_KEEPALIVE_S = 5.0  # как часто отдавать пустой кусок, пока ждём инструмент или модель после него
# дольше этого повторный прогон модели без первого куска keep-alive не прикрываем:
# дальше срабатывает предел паузы разговора (PART_IDLE_S) — зависшая модель остаётся сбоем
TOOL_FOLLOWUP_KEEPALIVE_LIMIT_S = 20.0
KEEPALIVE = ReplyPart("")  # пустой кусок: участник жив, ждёт инструмент или продолжение модели
BOUNDARY = ReplyPart("\n")  # граница предложения: сказанное до вызова уходит в озвучку сразу

Run = Callable[[list[ChatMessage], Sequence[ToolSpec]], AsyncIterator[ReplyPart]]  # Executor.run


def member_stream(
    source: str,
    toolbox: ToolBox | None,
    run: Run,
    messages: list[ChatMessage],
    tools: tuple[Sequence[ToolSpec], Sequence[ToolSpec]],
    observe: ToolObserver | None = None,
) -> AsyncIterator[ReplyPart]:
    """Поток участника source; tools — (все его инструменты, инструменты вызывающего сети).

    Без ящика — просто run. С ящиком — ToolLoop: delegate и инструменты
    вызывающего отдаются дальше, остальные вызовы выполняет ящик.
    observe — получает начало и конец каждого вызова ящика.
    """
    offered, extra = tools
    if toolbox is None:
        return run(messages, offered)
    passthrough = frozenset({DELEGATE_TOOL, *(t.name for t in extra)})
    return ToolLoop(source, toolbox, passthrough, observe=observe).run(run, messages, offered)


class ToolLoop:
    """Ответ участника с вызовами инструментов ящика.

    Куски модели отдаются как есть, кроме вызовов инструментов ящика: такой вызов
    выполняется сразу (сказанное до него уже отдано, после него — граница
    предложения «\\n»), в сообщения добавляются assistant со сказанным до вызова
    текстом и вызовом и tool с результатом. Поток модели дочитывается до конца, и
    если были вызовы — модель запускается снова с дополненными сообщениями.
    Вызовы из passthrough (delegate, инструменты вызывающего) отдаются дальше без
    выполнения. Вызов сверх max_calls — кусок TOOL_FAILURE_PHRASE с failure и
    конец ответа.

    Пока ждём инструмент или первый кусок повторного прогона, а участник уже
    что-то отдал, — пустой кусок KEEPALIVE каждые keepalive_s: пауза между
    кусками не должна выглядеть как зависшая модель. До первого отданного куска
    с текстом keep-alive нет: первый кусок ждёт разговор (с сигналом «думаю»).
    Повторный прогон модели прикрывается не дольше followup_limit_s: дальше
    keep-alive нет, и зависшую модель ловит предел паузы разговора.
    """

    def __init__(
        self,
        source: str,
        toolbox: ToolBox,
        passthrough: frozenset[str],
        max_calls: int = MAX_TOOL_CALLS,
        keepalive_s: float | None = None,
        followup_limit_s: float | None = None,
        observe: ToolObserver | None = None,
    ) -> None:
        """source — id участника (для журнала); passthrough — имена вызовов, которые не выполняются.

        keepalive_s — период keep-alive, followup_limit_s — сколько прикрывать повторный
        прогон (None — TOOL_KEEPALIVE_S и TOOL_FOLLOWUP_KEEPALIVE_LIMIT_S на момент создания).
        observe — получает начало и конец каждого вызова ящика (отменённый — конец с ok=False);
        конец несёт аргументы вызова и текст ответа инструмента (его видит модель).
        """
        self._source = source
        self._observe = observe
        self._toolbox = toolbox
        self._passthrough = passthrough
        self._max_calls = max_calls
        self._keepalive_s = TOOL_KEEPALIVE_S if keepalive_s is None else keepalive_s
        self._followup_limit_s = (
            TOOL_FOLLOWUP_KEEPALIVE_LIMIT_S if followup_limit_s is None else followup_limit_s
        )
        self._calls = 0
        self._gave = False  # участник уже отдал наружу кусок модели с текстом

    async def run(
        self, run: Run, messages: list[ChatMessage], tools: Sequence[ToolSpec]
    ) -> AsyncIterator[ReplyPart]:
        """Куски ответа участника; run — Executor.run участника; tools — все его инструменты."""
        known = frozenset(t.name for t in tools) - self._passthrough
        follow_up = False
        while True:
            added: list[ChatMessage] = []
            stream = run(messages, tools)
            parts = self._round(self._alive_first(stream) if follow_up else stream, known, added)
            async with closing(stream), closing(parts):
                async for part in parts:
                    yield part
            if not added:
                return
            messages = [*messages, *added]  # новый список: прежний мог остаться у модели
            follow_up = True

    async def _round(
        self, stream: AsyncIterator[ReplyPart], known: frozenset[str], added: list[ChatMessage]
    ) -> AsyncIterator[ReplyPart]:
        """Куски одного прогона модели; сообщения выполненных вызовов — в added (предел — added пуст)."""
        said: list[str] = []
        async with closing(stream):
            async for part in stream:
                call = part.tool_call
                if call is None or call.name in self._passthrough:
                    said.append(part.text)
                    self._gave = self._gave or bool(part.text)  # пустые и вызовы сеть может проглотить
                    yield part
                    continue
                if self._calls >= self._max_calls:
                    _log.warning("«%s» вызывает инструменты больше %d раз", self._source, self._max_calls)
                    added.clear()
                    yield ReplyPart(TOOL_FAILURE_PHRASE, failure=True)
                    return
                self._calls += 1
                if _open_sentence("".join(said)):
                    yield BOUNDARY
                result: list[ToolResult] = []
                async with closing(self._alive(self._call(call, known), result)) as waiting:
                    async for keepalive in waiting:
                        yield keepalive
                added += _exchange("".join(said), call, result[0])
                said.clear()

    async def _alive_first(self, stream: AsyncIterator[ReplyPart]) -> AsyncIterator[ReplyPart]:
        """Куски повторного прогона; пока нет первого — keep-alive (не дольше followup_limit_s)."""
        first: list[ReplyPart | None] = []
        waited = self._alive(anext(stream, None), first, self._followup_limit_s)
        async with closing(waited) as waiting:
            async for keepalive in waiting:
                yield keepalive
        if first[0] is None:
            return
        yield first[0]
        async for part in stream:
            yield part

    async def _alive[T](
        self, waited: Awaitable[T], result: list[T], limit_s: float | None = None
    ) -> AsyncIterator[ReplyPart]:
        """Ждёт waited, результат — в result; пока ждём и участник уже отдавал текст — KEEPALIVE.

        limit_s — после стольких секунд ожидания keep-alive больше нет (None — без предела).
        Закрыли раньше — ожидание отменяется. Ничего не отдано — ждём прямо, без
        отдельной задачи (keep-alive всё равно не нужен).
        """
        if not self._gave:
            result.append(await waited)
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (limit_s if limit_s is not None else float("inf"))
        task = asyncio.ensure_future(waited)
        try:
            while not (await asyncio.wait({task}, timeout=self._keepalive_s))[0]:
                if loop.time() >= deadline:
                    await asyncio.wait({task})  # дальше без keep-alive: пусть судит предел разговора
                    break
                yield KEEPALIVE
            result.append(task.result())
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)  # и забрать исключение, если было

    async def _call(self, call: ToolCall, known: frozenset[str]) -> ToolResult:
        """Результат вызова: ящик выполняет известный инструмент, неизвестный — ошибка без вызова.

        Ящик по договору не бросает исключений; бросил всё же — ошибка для модели, ход не падает.
        """
        if call.name not in known:
            _log.warning("«%s» вызывает неизвестный инструмент %r", self._source, call.name)
            return ToolResult(UNKNOWN_TOOL.format(name=call.name), is_error=True)
        _log.info("«%s» вызывает инструмент %s", self._source, call.name)
        self._notify(ToolUse(self._source, call.name, "started"))
        result = ToolResult(TOOL_CRASHED.format(name=call.name), is_error=True)
        try:
            result = await self._toolbox.call(call.name, call.arguments, person=None)
        except Exception:  # noqa: BLE001 — сбой ящика не должен ронять ход
            _log.exception("Ящик инструментов упал на вызове %s", call.name)
            return result
        finally:  # и при отмене: подсветка инструмента не должна остаться гореть
            ok, arguments = not result.is_error, call.arguments
            finished = ToolUse(
                self._source, call.name, "finished", ok=ok, arguments=arguments, result=result.text
            )
            self._notify(finished)
        if result.is_error:
            _log.warning("Инструмент %s вернул ошибку: %s", call.name, result.text)
        return result

    def _notify(self, use: ToolUse) -> None:
        """Сообщает наблюдателю о вызове; его сбой ход не роняет."""
        if self._observe is None:
            return
        try:
            self._observe(use)
        except Exception:  # noqa: BLE001 — подсветка вторична, ход важнее
            _log.exception("Наблюдатель вызовов инструментов упал")


def _open_sentence(said: str) -> bool:
    """True, если в сказанном есть текст, а границы предложения («\\n») в конце нет."""
    return bool(said.strip()) and not said.endswith("\n")


def _exchange(said: str, call: ToolCall, result: ToolResult) -> list[ChatMessage]:
    """Сообщения одного вызова: assistant со сказанным до вызова и вызовом, tool с результатом."""
    return [
        ChatMessage("assistant", said, tool_calls=(call,)),
        ChatMessage("tool", result.text, tool_name=call.name),
    ]
