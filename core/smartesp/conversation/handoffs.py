"""Передача задачи в ходе: путь хода, ожидание цели, ответы исполнителей по предложениям.

Исполнитель (сеть исполнителей) отдаёт ReplyPart(handoff=…) и сразу за ним
куски цели. Первый кусок цели ждём как первый кусок ответа: с сигналом «думаю»
и своим пределом; не дождались — звучит фраза «Не получилось ответить вовремя…», ход — ошибка.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from smartesp.contracts import Executor, ExecutorError, Handoff, Identified, ReplyPart

from .sentences import DEFAULT_STYLE, clean_for_speech, split_sentences, strip_style_tag, take_style
from .streams import closing, first_part, next_part
from .turn import Turn

_log = logging.getLogger(__name__)

DELEGATE_FIRST_PART_LIMIT_S = 90.0  # дольше первого куска цели передачи не ждём
LIVE_POLL_S = 0.1  # как часто проверять, актуален ли ход, пока ждём цель
TIMEOUT_PHRASE = "Не получилось ответить вовремя, спроси попозже."  # цель не ответила в срок
SILENT_PHRASE = "{name} сейчас не отвечает."  # цель ничего не сказала
CANNED_PHRASE = "Минутку, сейчас узнаю."  # вызов передачи без фразы: говорим за диспетчера
ENTRY_ID = "entry"  # id входного исполнителя, который своего id не знает


@dataclass(frozen=True)
class Waiting:
    """Как ждать куски ответа хода (секунды).

    thinking — сигнал «думаю» колонке; is_live — актуален ли ход;
    thinking_interval_s — период «думаю»; part_idle_s — предел паузы между
    кусками; delegate_limit_s — предел первого куска цели после передачи.
    """

    thinking: Callable[[], Awaitable[None]]
    is_live: Callable[[], bool]
    thinking_interval_s: float
    part_idle_s: float
    delegate_limit_s: float
    live_poll_s: float = LIVE_POLL_S


@dataclass(frozen=True)
class Sentence:
    """Предложение ответа; opens_answer — первое в ответе своего исполнителя (входного или цели)."""

    text: str
    opens_answer: bool


def entry_id(executor: Executor) -> str:
    """Начало пути хода: id входного исполнителя или ENTRY_ID, если он его не знает."""
    return executor.id if isinstance(executor, Identified) else ENTRY_ID


def record_handoff(turn: Turn, handoff: Handoff) -> None:
    """Записывает передачу в ход: цель — в путь, передачу — в список, начало ответа цели."""
    turn.path.append(handoff.target)
    turn.delegations.append(handoff)
    turn.breaks.append(len(turn.answer))


async def collect(
    turn: Turn, first: ReplyPart | None, parts: AsyncIterator[ReplyPart], waiting: Waiting
) -> AsyncIterator[ReplyPart]:
    """Отдаёт заранее взятый первый кусок и остальные; копит текст ответа и передачи.

    После куска с handoff первый кусок цели ждём с «думаю» (без сказанного до
    передачи текста — «думаю» сразу) не дольше delegate_limit_s; не дождались —
    фраза TIMEOUT_PHRASE с failure и конец. Цель так ничего и не сказала (поток
    кончился или замолк дольше part_idle_s) — фраза SILENT_PHRASE с failure.
    Ход стал неактуальным, пока ждём цель, — заканчиваем сразу. Пауза между
    кусками дольше part_idle_s в остальных случаях — ExecutorError.
    """
    part, target_start = first, 0
    while part is not None:
        if part.handoff is not None:
            canned = _canned_part(turn)
            if canned is not None:
                _take(turn, canned)
                yield canned
            target_start = len(turn.answer)
        _take(turn, part)
        yield part
        try:
            part = await _following(turn, part, parts, waiting)
        except ExecutorError as error:
            if part.handoff is None and not _target_silent(turn, target_start):
                raise
            _log.warning("Колонка %s: цель передачи не ответила: %s", turn.device_name, error)
            failure = _timeout_part() if part.handoff is not None else _silent_part(turn)
            _take(turn, failure)
            yield failure
            return
    if _target_silent(turn, target_start) and waiting.is_live():
        _log.warning("Колонка %s: цель передачи ничего не сказала", turn.device_name)
        failure = _silent_part(turn)
        _take(turn, failure)
        yield failure


def _spoken(turn: Turn) -> bool:
    """True, если в ходе уже сказано что-то, что можно озвучить (метка стиля и «…» не считаются)."""
    return bool(clean_for_speech(strip_style_tag("".join(turn.answer))[1]))


def _canned_part(turn: Turn) -> ReplyPart | None:
    """Фраза за диспетчера, если он вызвал передачу молча; только для первой передачи хода."""
    if turn.delegations or _spoken(turn):
        return None
    _log.info("Колонка %s: вызов без фразы — говорим «Минутку…»", turn.device_name)
    return ReplyPart(CANNED_PHRASE)


def _take(turn: Turn, part: ReplyPart) -> None:
    """Учитывает кусок в ходе: передачу, текст, время первого текста, ошибку.

    Фраза об ошибке (failure) начинает в ответе новый кусок и помечает ход ошибкой.
    """
    if part.handoff is not None:
        record_handoff(turn, part.handoff)
        return
    if part.failure:
        turn.breaks.append(len(turn.answer))
        turn.failed = True
    if part.text and turn.first_text_ms is None:
        turn.first_text_ms = turn.elapsed_ms()
    turn.answer.append(part.text)


def _timeout_part() -> ReplyPart:
    """Фраза «не успела»: цель не дала первый кусок в срок."""
    return ReplyPart(TIMEOUT_PHRASE, failure=True)


def _silent_part(turn: Turn) -> ReplyPart:
    """Фраза «<Имя> сейчас не отвечает.» о последней цели передачи."""
    return ReplyPart(SILENT_PHRASE.format(name=turn.delegations[-1].target_name), failure=True)


def _target_silent(turn: Turn, target_start: int) -> bool:
    """True, если в ходе была передача, а цель не сказала ничего, что можно озвучить."""
    said = "".join(turn.answer[target_start:])
    return bool(turn.delegations) and not clean_for_speech(strip_style_tag(said)[1])


async def _following(
    turn: Turn, previous: ReplyPart, parts: AsyncIterator[ReplyPart], waiting: Waiting
) -> ReplyPart | None:
    """Следующий кусок: после передачи — первый кусок цели, иначе — с пределом паузы."""
    if previous.handoff is not None:
        return await _target_first(turn, parts, waiting)
    return await next_part(parts, waiting.part_idle_s)


async def _target_first(turn: Turn, parts: AsyncIterator[ReplyPart], waiting: Waiting) -> ReplyPart | None:
    """Первый кусок цели передачи или None (цель промолчала или ход стал неактуальным).

    Не дождались за delegate_limit_s — ExecutorError.
    """
    if not _spoken(turn):  # до передачи ничего не сказано — колонка не должна ждать молча
        await waiting.thinking()
    try:
        async with asyncio.timeout(None) as deadline:
            watcher = asyncio.create_task(_watch(waiting.is_live, deadline, waiting.live_poll_s))
            try:
                return await first_part(
                    parts, waiting.thinking, waiting.thinking_interval_s, waiting.delegate_limit_s
                )
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
    except TimeoutError:
        _log.info("Колонка %s: ход прерван, пока ждали цель передачи", turn.device_name)
        return None


async def _watch(is_live: Callable[[], bool], deadline: asyncio.Timeout, poll_s: float) -> None:
    """Обрывает ожидание (срок deadline — сейчас), как только ход перестал быть актуальным."""
    while is_live():
        await asyncio.sleep(poll_s)
    deadline.reschedule(asyncio.get_running_loop().time())


class _Segments:
    """Делит поток кусков на ответы: исполнителя до передачи и отдельно каждую фразу об ошибке."""

    def __init__(self, parts: AsyncIterator[ReplyPart]) -> None:
        self._parts = parts
        self._pending: ReplyPart | None = None  # фраза об ошибке, с которой начнётся следующий ответ
        self.more = True  # после текущего ответа будет следующий

    async def next(self) -> AsyncIterator[ReplyPart]:
        """Куски следующего ответа; кусок передачи не отдаётся; общий поток не закрывает."""
        self.more = False
        if self._pending is not None:
            yield self._pending
            self._pending = None
        async for part in self._parts:
            if part.handoff is not None or part.failure:
                self._pending = part if part.failure else None
                self.more = True
                return
            yield part


async def answer_sentences(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[Sentence]:
    """Режет поток кусков на предложения отдельно для каждого ответа.

    Ответ — куски исполнителя до передачи или фраза об ошибке. На их границе
    недоговорённое предложение отдаётся сразу (фраза «Сейчас спрошу…» звучит,
    пока ждём цель), а следующий ответ начинается с нового предложения с
    opens_answer=True.
    """
    segments = _Segments(parts)
    while segments.more:
        async with closing(split_sentences(segments.next())) as sentences:
            opens = True
            async for text in sentences:
                yield Sentence(text, opens)
                opens = False


def speech_text(turn: Turn, sentence: Sentence, styles: list[str]) -> str:
    """Текст предложения для озвучки.

    Метка стиля в начале ответа исполнителя снимается всегда, а применяется,
    только если стиль хода ещё не выбран (DEFAULT_STYLE): стиль входного
    сохраняется и для цели передачи.
    """
    text = sentence.text
    if sentence.opens_answer:
        style, text = take_style(text, styles)
        if turn.style == DEFAULT_STYLE:
            turn.style = style
    return clean_for_speech(text)
