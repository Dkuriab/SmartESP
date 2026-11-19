"""Ход через API: вопрос текстом или голосом (PCM) — тот же путь, что с колонки, ответ текстом.

Обработчики, сеть исполнителей с инструментами и передачами, история и события ленты —
как у хода с колонки (origin "api", source, person). Звука нет: колонке ничего не шлём,
«думаю» никому не нужно, ход актуален до конца. Запоздавший ответ не откладывается и не
объявляется: весь ход укладывается в limit_s (клиент ждёт 60 с), не уложился — честная
фраза LATE_PHRASE. Одновременно идут не больше MAX_CONCURRENT ходов: следующий ждёт
место до QUEUE_WAIT_S (ожидание — в счёт limit_s), не дождался — AskUnavailable (BUSY).
"""

import asyncio
import itertools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from smartesp.contracts import (
    Analyzer,
    Annotation,
    Answer,
    AskUnavailable,
    ChatMessage,
    Executor,
    ExecutorError,
    Question,
    SpeechToText,
    Utterance,
)

from . import handoffs
from .activity import Publish, watched
from .history import History
from .sentences import is_meaningless
from .steps import begin, end, hear, remember, settle, understand
from .streams import closing, first_part
from .turn import API_ORIGIN, Turn, answer_text, turn_id
from .turn_tasks import TurnTasks

_log = logging.getLogger(__name__)

ASK_LIMIT_S = 55.0  # весь ход через API, включая передачу задачи: клиент (бот) ждёт 60 с
API_DEVICE = "api"  # device_id ходов через API в событиях
LATE_PHRASE = "Не успела ответить, спроси попозже."  # ход не уложился в limit_s
NOT_HEARD = "Не расслышала."  # в голосовом нечего распознать или распознано бессмысленное
FAILED_PHRASE = "Не получилось ответить, попробуй ещё раз."  # сбой без единого слова ответа
NOT_READY = "Кузя ещё не готов: части ядра греются"
STOPPING = "Кузя останавливается"
BUSY = "Кузя занят другими вопросами, спроси чуть позже"
MAX_CONCURRENT = 2  # ходов через API одновременно: модель общая с колонками
QUEUE_WAIT_S = 10.0  # сколько вопрос ждёт места, пока идут другие ходы через API
CHANNEL_NOTE = "{title}: вопрос не с колонки, ответ прочитают текстом"  # пометка для промпта


@dataclass(frozen=True)
class AskParts:
    """Снимок частей на начало хода через API; распознавания может не быть (нужно только голосу)."""

    stt: SpeechToText | None
    analyze: Analyzer
    executor: Executor


def source_title(source: str) -> str:
    """Имя источника для ленты и промпта: "telegram" → "Telegram"."""
    return source[:1].upper() + source[1:]


def reply_text(turn: Turn) -> str:
    """Ответ клиенту: текст ответа хода; нечего распознать — NOT_HEARD; сбой без слов — FAILED_PHRASE."""
    if turn.meaningless:
        return NOT_HEARD
    return answer_text(turn) or FAILED_PHRASE


async def _no_signal() -> None:
    """«Думаю» некому слать: у хода через API нет колонки."""


class ApiTurns:
    """Ведёт ходы через API в общем наборе задач ходов (их ждут drain и wait_turns)."""

    def __init__(
        self,
        history: History,
        publish: Publish,
        tasks: TurnTasks,
        parts: Callable[[], AskParts | None],
        first_part_limit_s: float,
        part_idle_s: float,
        limit_s: float = ASK_LIMIT_S,
    ) -> None:
        """parts() — текущие части или None (ядро не готово); пределы — в секундах.

        first_part_limit_s — первый кусок ответа; part_idle_s — пауза между кусками;
        limit_s — весь ход (он же предел первого куска цели передачи).
        """
        self._history = history
        self._publish = publish
        self._tasks = tasks
        self._parts = parts
        self._first_part_limit_s = first_part_limit_s
        self._part_idle_s = part_idle_s
        self._limit_s = limit_s
        self._numbers = itertools.count(1)
        self._slots = asyncio.Semaphore(MAX_CONCURRENT)
        self._stopped = asyncio.Event()  # ядро останавливается: будит вопросы в очереди

    @property
    def accepting(self) -> bool:
        """True, пока ходы принимаются; False — ядро останавливается."""
        return not self._stopped.is_set()

    @accepting.setter
    def accepting(self, value: bool) -> None:
        """False — новых ходов не берём, вопросы в очереди сразу получают STOPPING."""
        if value:
            self._stopped.clear()
        else:
            self._stopped.set()

    async def ask(self, question: Question) -> Answer:
        """Проводит ход отдельной задачей и возвращает ответ текстом.

        Ядро не готово (нет частей, а голосу — распознавания) или останавливается —
        AskUnavailable; не дождался места за QUEUE_WAIT_S — тоже (BUSY). Готовность и части
        проверяются и до очереди, и после неё: за ожидание ядро могло начать остановку или
        сменить исполнителя. Отмена ожидания отменяет и ход.
        """
        self._ready_parts(question)  # не готово — отказ сразу, без очереди
        received = time.monotonic()
        if not await self._admit():
            raise AskUnavailable(BUSY if self.accepting else STOPPING)
        try:
            parts = self._ready_parts(question)  # свежий снимок после очереди
            turn = self._new_turn(question, received)
            task = self._tasks.start(
                self._handle(turn, parts), name=f"turn {API_DEVICE}#{turn.utterance.turn}"
            )
        except BaseException:
            self._slots.release()
            raise
        task.add_done_callback(lambda _: self._slots.release())  # место свободно, когда ход кончился
        try:
            await asyncio.wait((task,))
        except asyncio.CancelledError:
            task.cancel()
            raise
        if task.cancelled():  # ход отменила остановка ядра
            raise AskUnavailable(STOPPING)
        return Answer(reply_text(turn), str(turn_id(turn)))

    def _ready_parts(self, question: Question) -> AskParts:
        """Текущие части; ядро останавливается, не готово или голосу нет распознавания — AskUnavailable."""
        parts = self._parts() if self.accepting else None
        if parts is None or (question.pcm and parts.stt is None):
            raise AskUnavailable(NOT_READY if self.accepting else STOPPING)
        return parts

    async def _admit(self) -> bool:
        """Ждёт место среди идущих ходов через API: True — место занято за нами.

        False — не дождались за QUEUE_WAIT_S или ядро начало останавливаться (тогда сразу).
        """
        acquire = asyncio.create_task(self._slots.acquire())
        stopped = asyncio.create_task(self._stopped.wait())
        try:
            await asyncio.wait((acquire, stopped), timeout=QUEUE_WAIT_S, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:  # отменили ожидающего: занятое место возвращаем
            if await _settle(acquire, stopped):
                self._slots.release()
            raise
        acquired = await _settle(acquire, stopped)
        if not acquired:
            _log.warning("Ход через API отклонён: %s", "очередь" if self.accepting else "остановка")
        return acquired

    def _new_turn(self, question: Question, received: float) -> Turn:
        """Ход вопроса с новым номером; received — когда вопрос пришёл (от него считается limit_s)."""
        number = next(self._numbers)
        utterance = Utterance(
            API_DEVICE, number, question.pcm, received, text=question.text, origin=API_ORIGIN
        )
        title = source_title(question.source)
        return Turn(
            utterance, title, received, text=question.text, source=question.source, person=question.person
        )

    async def _handle(self, turn: Turn, parts: AskParts) -> None:
        """Ход целиком в пределах limit_s от прихода вопроса; любая ошибка (кроме отмены) — ход с ошибкой."""
        activity = begin(turn, self._publish)
        try:
            async with asyncio.timeout(max(0.0, turn.received_at + self._limit_s - time.monotonic())):
                await self._converse(turn, parts)
        except TimeoutError:
            _log.warning(
                "%s: ход %s не уложился в %g с", turn.device_name, turn.utterance.turn, self._limit_s
            )
            _late(turn)
        except Exception:
            _log.error("%s: ход %s упал", turn.device_name, turn.utterance.turn, exc_info=True)
            turn.failed = True
        finally:
            end(turn, activity, self._publish)

    async def _converse(self, turn: Turn, parts: AskParts) -> None:
        """Голос распознаёт; понимает, отвечает и записывает завершённый ход в историю."""
        if not turn.text:  # голосовое сообщение
            if turn.utterance.pcm and parts.stt is not None:
                await hear(turn, parts.stt, self._publish)
            if is_meaningless(turn.text):
                turn.meaningless = True
                return
        messages = await understand(turn, parts.analyze, self._history, "", _context(turn))
        await self._reply(turn, parts.executor, messages)
        remember(turn, self._history)

    async def _reply(self, turn: Turn, executor: Executor, messages: list[ChatMessage]) -> None:
        """Читает ответ сети целиком (с передачами) в turn; сбой исполнителя — ход с ошибкой."""
        turn.path = [handoffs.entry_id(executor)]
        try:
            async with closing(watched(executor.run(messages))) as stream:
                first = await first_part(
                    stream, _no_signal, self._first_part_limit_s, self._first_part_limit_s
                )
                async with closing(handoffs.collect(turn, first, stream, self._waiting())) as parts:
                    async for _ in parts:
                        pass
        except ExecutorError as error:
            _log.warning("%s: исполнитель не ответил: %s", turn.device_name, error)
            turn.failed = True
            return
        turn.completed = not turn.failed
        settle(turn)

    def _waiting(self) -> handoffs.Waiting:
        """Ожидание цели передачи: без «думаю», ход всегда актуален, ответ не откладывается."""
        return handoffs.Waiting(
            _no_signal,
            lambda: True,
            self._limit_s,
            self._part_idle_s,
            self._limit_s,
        )


async def _settle(acquire: asyncio.Task[bool], stopped: asyncio.Task[bool]) -> bool:
    """Снимает ожидания места и остановки; True — место всё-таки занято (его надо вернуть или занять)."""
    for task in (acquire, stopped):
        task.cancel()
    await asyncio.gather(acquire, stopped, return_exceptions=True)
    return not acquire.cancelled()


def _context(turn: Turn) -> list[Annotation]:
    """Пометки для промпта: откуда вопрос и кто спрашивает."""
    notes = [Annotation(CHANNEL_NOTE.format(title=turn.device_name), turn.source, label="канал")]
    if turn.person:
        notes.append(Annotation(turn.person, turn.source, label="человек"))
    return notes


def _late(turn: Turn) -> None:
    """Ход не уложился в предел: к сказанному — фраза LATE_PHRASE, ход с ошибкой."""
    turn.breaks.append(len(turn.answer))
    turn.answer.append(LATE_PHRASE)
    turn.failed = True
