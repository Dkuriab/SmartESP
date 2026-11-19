"""Ход через API: вопрос текстом или голосом (PCM) — тот же путь, что с колонки, ответ текстом.

Обработчики, сеть исполнителей с инструментами и передачами, история и события ленты —
как у хода с колонки (origin "api", source, person). Звука нет: колонке ничего не шлём,
«думаю» никому не нужно, ход актуален до конца. Запоздавший ответ не откладывается и не
объявляется: весь ход укладывается в limit_s (клиент ждёт 60 с), не уложился — честная
фраза LATE_PHRASE.
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
        self.accepting = True  # ядро останавливается — новых ходов не берём

    async def ask(self, question: Question) -> Answer:
        """Проводит ход отдельной задачей и возвращает ответ текстом.

        Ядро не готово (нет частей, а голосу — распознавания) или останавливается —
        AskUnavailable. Отмена ожидания отменяет и ход.
        """
        parts = self._parts() if self.accepting else None
        if parts is None or (question.pcm and parts.stt is None):
            raise AskUnavailable(NOT_READY if self.accepting else STOPPING)
        number = next(self._numbers)
        now = time.monotonic()
        utterance = Utterance(API_DEVICE, number, question.pcm, now, text=question.text, origin=API_ORIGIN)
        title = source_title(question.source)
        turn = Turn(utterance, title, now, text=question.text, source=question.source, person=question.person)
        task = self._tasks.start(self._handle(turn, parts), name=f"turn {API_DEVICE}#{number}")
        try:
            await asyncio.wait((task,))
        except asyncio.CancelledError:
            task.cancel()
            raise
        if task.cancelled():  # ход отменила остановка ядра
            raise AskUnavailable(STOPPING)
        return Answer(reply_text(turn), str(turn_id(turn)))

    async def _handle(self, turn: Turn, parts: AskParts) -> None:
        """Ход целиком в пределах limit_s; любая ошибка (кроме отмены) — ход с ошибкой."""
        activity = begin(turn, self._publish)
        try:
            async with asyncio.timeout(self._limit_s):
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
