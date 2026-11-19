"""Передача задачи в ходе: путь хода, ожидание цели, ответы исполнителей по предложениям.

Исполнитель (сеть исполнителей) отдаёт ReplyPart(handoff=…) и сразу за ним
куски цели. Первый кусок цели ждём как первый кусок ответа: с сигналом «думаю»
и своим пределом; не дождались — звучит фраза «Не успела…», ход — ошибка.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from smartesp.contracts import Executor, ExecutorError, Handoff, Identified, ReplyPart

from .sentences import DEFAULT_STYLE, clean_for_speech, split_sentences, take_style
from .streams import closing, first_part, next_part
from .turn import Turn, answer_text

_log = logging.getLogger(__name__)

DELEGATE_FIRST_PART_LIMIT_S = 90.0  # дольше первого куска цели передачи не ждём
LIVE_POLL_S = 0.1  # как часто проверять, актуален ли ход, пока ждём цель
TIMEOUT_PHRASE = "Не успела ответить, спроси попозже."  # цель не ответила в срок
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
    отдаём фразу TIMEOUT_PHRASE с failure и заканчиваем. Ход стал неактуальным,
    пока ждём цель, — заканчиваем сразу. Кусок failure помечает ход ошибкой.
    Пауза между остальными кусками дольше part_idle_s — ExecutorError.
    """
    part = first
    while part is not None:
        if part.handoff is not None:
            record_handoff(turn, part.handoff)
        else:
            _take(turn, part)
        yield part
        if part.handoff is None:
            part = await next_part(parts, waiting.part_idle_s)
            continue
        try:
            part = await _target_first(turn, parts, waiting)
        except ExecutorError as error:
            _log.warning("Колонка %s: цель передачи не ответила: %s", turn.device_name, error)
            timeout = ReplyPart(TIMEOUT_PHRASE, failure=True)
            _take(turn, timeout)
            yield timeout
            return


def _take(turn: Turn, part: ReplyPart) -> None:
    """Копит текст куска; кусок failure помечает ход ошибкой со сказанной фразой."""
    turn.answer.append(part.text)
    if part.failure:
        turn.failed = True
        turn.failure_phrase = True


async def _target_first(turn: Turn, parts: AsyncIterator[ReplyPart], waiting: Waiting) -> ReplyPart | None:
    """Первый кусок цели передачи или None (цель промолчала или ход стал неактуальным).

    Не дождались за delegate_limit_s — ExecutorError.
    """
    if not answer_text(turn):  # до передачи ничего не сказано — колонка не должна ждать молча
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


class _Segment:
    """Куски ответа одного исполнителя: до передачи или до конца потока."""

    def __init__(self, parts: AsyncIterator[ReplyPart]) -> None:
        self._parts = parts
        self.handed_off = False  # кончился передачей: дальше — ответ цели

    async def parts(self) -> AsyncIterator[ReplyPart]:
        """Куски до передачи (её кусок не отдаётся); общий поток не закрывает."""
        async for part in self._parts:
            if part.handoff is not None:
                self.handed_off = True
                return
            yield part


async def answer_sentences(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[Sentence]:
    """Режет поток кусков на предложения отдельно для каждого исполнителя.

    На передаче недоговорённое входным предложение отдаётся сразу (фраза
    «Сейчас спрошу…» звучит, пока ждём цель), а ответ цели начинается с нового
    предложения с opens_answer=True.
    """
    while True:
        segment = _Segment(parts)
        async with closing(split_sentences(segment.parts())) as sentences:
            opens = True
            async for text in sentences:
                yield Sentence(text, opens)
                opens = False
        if not segment.handed_off:
            return


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
