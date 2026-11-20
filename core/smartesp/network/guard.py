"""Страховка честности входного исполнителя: проверка первого предложения до озвучки.

Нарушение — ответ без вызова инструмента, который (a) первым предложением утверждает, что
действие сделано или делается («Поставила таймер», «Включаю музыку»), (b) пуст или (c) пишет
вызов инструмента текстом (JSON, «имя(…)»). Тогда сказанное не звучит: один повторный прогон
с тем же диалогом и напоминанием REMINDER (без нечестного ответа); снова нарушение — честная
фраза. Обычный ответ отдаётся, как только закончено первое предложение (разговор всё равно
копит его целиком до озвучки); утверждение держится до вызова инструмента (отдаётся, как только
инструмент начал работать) или до конца.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Callable
from typing import Literal

from smartesp.contracts import ChatMessage, ReplyPart, ToolObserver, ToolUse

from .claim_check import claims_action, first_sentence, opens_structure, spells_tool_call
from .dialog import closing, speakable

_log = logging.getLogger(__name__)

REMINDER = "Ты не вызвал инструмент. Вызови нужный инструмент или честно скажи, что не можешь это сделать."
NO_TOOL_PHRASE = "Не получилось это сделать — у меня нет подходящего инструмента."
NOT_HEARD_PHRASE = "Не расслышала, повтори, пожалуйста."

Reason = Literal["claim", "empty", "syntax"]
Tag = Literal["", "retried", "fallback"]
# прогон участника: сообщения и наблюдатель его вызовов инструментов → куски
Start = Callable[[list[ChatMessage], ToolObserver], AsyncIterator[ReplyPart]]
_REASONS: dict[Reason, str] = {
    "claim": "утверждает, что сделал",
    "empty": "пустой ответ",
    "syntax": "вызов инструмента текстом",
}
_END = object()  # поток кончился
_CALLED = object()  # инструмент начал работу, пока ждали кусок


async def guarded(
    source: str, start: Start, messages: list[ChatMessage], names: frozenset[str], heard: bool
) -> AsyncIterator[ReplyPart]:
    """Куски ответа участника source под страховкой честности.

    start — прогон участника; names — имена его инструментов (для поиска вызова текстом);
    heard — вопрос человека непустой (иначе на пустой ответ — NOT_HEARD_PHRASE).
    """
    first = _Attempt(start, messages, names)
    async with closing(first.parts()) as parts:
        async for part in parts:
            yield part
    if first.violation is None:
        return
    reason, text = first.violation
    _log.info("«%s»: %s без инструмента (%r) — повторный прогон", source, _REASONS[reason], text)
    # без нечестного ответа в диалоге: с ним gpt-oss:20b в замере повторял ложь в 7 из 16 прогонов,
    # без него — 0 из 16
    second = _Attempt(start, [*messages, ChatMessage("system", REMINDER)], names, tag="retried")
    async with closing(second.parts()) as parts:
        async for part in parts:
            yield part
    if second.violation is None:
        return
    reason, text = second.violation
    _log.info("«%s»: снова %s (%r) — честная фраза", source, _REASONS[reason], text)
    phrase = NOT_HEARD_PHRASE if reason == "empty" and not heard else NO_TOOL_PHRASE
    yield ReplyPart(phrase, guard="fallback")


class _Attempt:
    """Один прогон участника: держит куски, пока не ясно, честен ли ответ.

    violation — (причина, сказанный текст), если прогон нарушил правило (тогда из него не
    отдано ничего); tag — метка guard для первого отданного куска.
    """

    def __init__(
        self, start: Start, messages: list[ChatMessage], names: frozenset[str], tag: Tag = ""
    ) -> None:
        self._start = start
        self._messages = messages
        self._names = names
        self._tag = tag
        self._called = asyncio.Event()
        self._pending: asyncio.Future[object] | None = None
        self.violation: tuple[Reason, str] | None = None

    async def parts(self) -> AsyncIterator[ReplyPart]:
        """Куски прогона: сначала придержанные (после решения), затем остальные как есть."""
        stream = self._start(self._messages, self._seen)
        async with closing(stream):
            try:
                held = await self._hold(stream)
                if held is None:
                    return
                for part in held:
                    yield self._tagged(part)
                async for part in self._rest(stream):
                    yield self._tagged(part)
            finally:
                await self._drop()  # до закрытия потока: генератор не читают двое

    async def _hold(self, stream: AsyncIterator[ReplyPart]) -> list[ReplyPart] | None:
        """Читает и держит куски до решения; честный ответ — придержанные куски, нарушение — None."""
        held: list[ReplyPart] = []
        text, claim = "", False
        while not self._called.is_set():
            item = await self._next(stream)
            if item is _CALLED:
                break
            if item is _END:
                return self._at_end(held, text)
            assert isinstance(item, ReplyPart)
            if item.tool_call is not None:  # передача или инструмент вызывающего: вызов был
                held.append(item)
                break
            if not item.text:
                continue  # keep-alive: держим молча, разговор и так ждёт первый кусок
            held.append(item)
            text += item.text
            verdict = self._judge(text, claim)
            if verdict == "release":
                break
            if verdict == "claim":
                claim = True
            elif verdict == "syntax":
                self.violation = ("syntax", text)
                return None
        return held

    def _judge(self, text: str, claim: bool) -> str:
        """Решение по накопленному тексту: release, claim (держать до вызова), syntax или wait."""
        if claim:
            return "claim"
        if opens_structure(text):
            return "syntax" if spells_tool_call(text, self._names) else "wait"
        sentence = first_sentence(text)
        if sentence is None:
            return "wait"
        if spells_tool_call(sentence, self._names):
            return "syntax"
        return "claim" if claims_action(sentence) else "release"

    def _at_end(self, held: list[ReplyPart], text: str) -> list[ReplyPart] | None:
        """Поток кончился: был вызов — придержанное как есть, иначе решение по всему тексту."""
        if self._called.is_set():
            return held
        if not speakable(text):
            self.violation = ("empty", text)
        elif spells_tool_call(text, self._names):
            self.violation = ("syntax", text)
        elif claims_action(first_sentence(text) or text.strip()):
            self.violation = ("claim", text)
        return None if self.violation is not None else held

    async def _next(self, stream: AsyncIterator[ReplyPart]) -> object:
        """Следующий кусок, _END или _CALLED — если инструмент начал работу раньше куска."""
        if self._pending is None:
            self._pending = asyncio.ensure_future(anext(stream, _END))
        waiter = asyncio.ensure_future(self._called.wait())
        try:
            await asyncio.wait({self._pending, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if not self._pending.done():
            return _CALLED
        pending, self._pending = self._pending, None
        return pending.result()

    async def _rest(self, stream: AsyncIterator[ReplyPart]) -> AsyncIterator[ReplyPart]:
        """Остаток потока как есть (сначала кусок, чтение которого уже начато)."""
        if self._pending is not None:
            pending, self._pending = self._pending, None
            item = await pending
            if item is _END:
                return
            assert isinstance(item, ReplyPart)
            yield item
        async for part in stream:
            yield part

    async def _drop(self) -> None:
        """Отменяет начатое чтение, если оно ещё идёт, и дожидается его."""
        pending, self._pending = self._pending, None
        if pending is not None and not pending.done():
            pending.cancel()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)

    def _seen(self, use: ToolUse) -> None:
        """Наблюдатель прогона: инструмент начал работу — вызов был."""
        if use.state == "started":
            self._called.set()

    def _tagged(self, part: ReplyPart) -> ReplyPart:
        """Первый отданный кусок получает метку tag (один раз)."""
        if not self._tag:
            return part
        tag, self._tag = self._tag, ""
        return dataclasses.replace(part, guard=tag)
