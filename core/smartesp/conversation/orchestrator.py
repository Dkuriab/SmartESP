"""Оркестратор хода: вопрос с колонки → STT → пометки → исполнитель → TTS → звук на колонку.

Ходы через API (текст или голос → ответ текстом) ведёт asking.ApiTurns в том же наборе задач.
"""

import functools
import logging
import time
from collections.abc import AsyncIterator

from smartesp.contracts import (
    CALL_CONTEXT,
    Analyzer,
    Announcer,
    Answer,
    CallContext,
    ChatMessage,
    DevicePort,
    EventSink,
    Executor,
    ExecutorError,
    Interruption,
    Question,
    SpeechToText,
    TaskBoard,
    TextToSpeech,
    Utterance,
)

from . import handoffs
from .activity import watched
from .asking import ASK_LIMIT_S, ApiTurns
from .history import History
from .late import LATE_LIMIT_S, LateAnswers
from .pausing import RESUME_WAIT_S, Pauses, Remainder, agrees, remainder_sentences, resume_style
from .slots import PartSlots
from .speaking import speak_answer, speak_text
from .steps import begin, end, hear, nothing_to_answer, remember, settle, understand
from .streams import closing, first_part, no_audio
from .turn import Parts, Turn, asks_question
from .turn_tasks import TurnTasks

_log = logging.getLogger(__name__)

ERROR_TONE = "error"  # сигнал колонке «ответить не получилось»
THINKING_TONE = "thinking"  # сигнал «думаю»: колонка продлевает ожидание ответа (у неё 15 с)
THINKING_INTERVAL_S = 8.0  # как часто слать «думаю», пока нет первого куска ответа
FIRST_PART_LIMIT_S = 45.0  # дольше первого куска не ждём: сигнал ошибки и пустой ответ
PART_IDLE_S = 20.0  # пауза исполнителя между кусками дольше этого — сбой посреди ответа


class Orchestrator(PartSlots):
    """Ведёт ходы разговора: на каждую реплику — своя задача."""

    def __init__(
        self,
        devices: DevicePort,
        stt: SpeechToText | None,
        analyze: Analyzer | None,
        executor: Executor | None,
        tts: TextToSpeech | None,
        history: History,
        *,
        events: EventSink | None = None,
        thinking_interval_s: float = THINKING_INTERVAL_S,
        first_part_limit_s: float = FIRST_PART_LIMIT_S,
        part_idle_s: float = PART_IDLE_S,
        delegate_limit_s: float = handoffs.DELEGATE_FIRST_PART_LIMIT_S,
        late_limit_s: float = LATE_LIMIT_S,
        ask_limit_s: float = ASK_LIMIT_S,
    ) -> None:
        """Колонки, распознавание, обработчики, исполнитель, синтез и история.

        Любую из четырёх частей можно не задать (None) — ядро не готово: ход получает сигнал
        ошибки и пустой ответ. events — куда публиковать события хода. В секундах:
        thinking_interval_s — период «думаю», пока ждём первый кусок; first_part_limit_s —
        предел первого куска; part_idle_s — следующего; delegate_limit_s — первого куска цели
        передачи; late_limit_s — запоздавшего ответа цели от начала хода; ask_limit_s — хода через API.
        """
        super().__init__(stt, analyze, executor, tts)
        self._devices = devices
        self._history = history
        self._events = events
        self._accepting = True
        self._thinking_interval_s = thinking_interval_s
        self._first_part_limit_s = first_part_limit_s
        self._part_idle_s = part_idle_s
        self._delegate_limit_s = delegate_limit_s
        self._tasks = TurnTasks()
        self._late = LateAnswers(devices, history, self._publish, part_idle_s, late_limit_s)
        self._asking = ApiTurns(
            history, self._publish, self._tasks, self._ask_parts, first_part_limit_s, part_idle_s, ask_limit_s
        )
        self._listen_after_question = True
        self._pauses = Pauses(devices)  # звучащие ответы: мягкое прерывание и остатки для «да»

    def use_announcer(self, announcer: Announcer) -> None:
        """Задаёт очередь объявлений: без неё запоздавший ответ не откладывается (TIMEOUT_PHRASE)."""
        self._late.announcer = announcer

    def use_tasks(self, tasks: TaskBoard) -> None:
        """Задаёт реестр «В работе»: в нём видно ожидание запоздавших ответов."""
        self._late.tasks = tasks

    def set_speech(self, proactive: bool, listen_after_question: bool) -> None:
        """Настройки речи: откладывать ли запоздавший ответ; слушать ли после вопроса Кузи.

        Уже отложенные ответы прозвучат, даже если proactive выключили.
        """
        self._late.proactive = proactive
        self._listen_after_question = listen_after_question

    async def interrupt(self, device_id: str, since: float) -> Interruption:
        """Мягкое прерывание ответа на колонке ради результата (договор Interrupt, см. pausing)."""
        return await self._pauses.interrupt(device_id, since)

    def speech(self, text: str) -> AsyncIterator[bytes]:
        """Озвучка текста текущим синтезом стилем по умолчанию (PCM); синтеза нет — RuntimeError."""
        tts = self._tts
        if tts is None:
            raise RuntimeError("синтез речи не готов")
        return speak_text(tts, text)

    async def ask(self, question: Question) -> Answer:
        """Ход через API без звука — ответ текстом (asking.ApiTurns); не готово — AskUnavailable."""
        return await self._asking.ask(question)

    def stop_accepting(self) -> None:
        """Перестаёт принимать ходы (новые получают сигнал ошибки и пустой ответ) и откладывать ответы."""
        self._accepting = self._asking.accepting = self._late.accepting = False

    async def drain(self, timeout_s: float) -> None:
        """Ждёт идущие ходы не дольше timeout_s секунд, затем отменяет оставшиеся и дожидается их.

        Ожидания запоздавших ответов отменяются сразу, без ожидания.
        """
        await self._late.cancel_all()
        await self._tasks.drain(timeout_s)
        await self._late.cancel_all()  # на случай хода, отложившего ответ до stop_accepting

    async def wait_turns(self, timeout_s: float) -> None:
        """Ждёт ходы, идущие сейчас (новые не ждёт), не дольше timeout_s секунд; ничего не отменяет."""
        await self._tasks.wait(timeout_s)

    async def run(self) -> None:
        """Бесконечно ждёт реплики и запускает на каждую свою задачу хода.

        Ошибка хода пишется в журнал и не останавливает run. При отмене run
        отменяет и дожидается незавершённых ходов и ожиданий запоздавших ответов.
        """
        try:
            while True:
                utterance = await self._devices.next_utterance()
                self._tasks.start(
                    self._handle(utterance, time.monotonic()),
                    name=f"turn {utterance.device_id}#{utterance.turn}",
                )
        finally:
            await self._tasks.cancel_all()  # отменённый ход ответ уже не отложит
            await self._late.cancel_all()

    def _publish(self, kind: str, data: dict[str, object]) -> None:
        """Публикует событие хода, если задан приёмник."""
        if self._events is not None:
            self._events.publish(kind, data)

    def _is_live(self, turn: Turn) -> bool:
        """True, пока ход актуален для колонки."""
        return self._devices.is_active(turn.utterance.device_id, turn.utterance.turn)

    async def _handle(self, utterance: Utterance, received_at: float) -> None:
        """Один ход целиком; любая ошибка (кроме отмены) — сигнал ошибки, колонка не молчит.

        Части берутся снимком в начале хода. Нет частей или приём остановлен —
        сигнал ошибки и пустой ответ без распознавания.
        """
        turn = Turn(utterance, self._devices.device_name(utterance.device_id), received_at)
        parts = self._snapshot() if self._accepting else None
        activity = begin(turn, self._publish)
        try:
            if parts is None:
                _log.warning("Колонка %s: ядро не готово или останавливается", turn.device_name)
                turn.failed = True
                await self._recover(turn)
            else:
                await self._converse(turn, parts)
        except Exception:
            _log.error("Колонка %s: ход %s упал", turn.device_name, utterance.turn, exc_info=True)
            turn.failed = True
            await self._recover(turn)
        finally:
            end(turn, activity, self._publish)
        if self._listen_after_question and asks_question(turn):
            await self._devices.listen_after(utterance.device_id, utterance.turn)

    async def _converse(self, turn: Turn, parts: Parts) -> None:
        """Распознаёт, понимает, отвечает и записывает ход в историю; «да» — продолжение остатка."""
        await hear(turn, parts.stt, self._publish)
        if nothing_to_answer(turn):
            await self._play(turn, no_audio())
            return
        if not self._is_live(turn):
            return
        remainder = self._pauses.claim(turn.utterance.device_id)
        if remainder is not None and agrees(turn.text):
            await self._resume(turn, parts.tts, remainder)
        else:
            messages = await understand(turn, parts.analyze, self._history, turn.device_name)
            await self._reply(turn, parts, messages)
        if self._is_live(turn) or turn.paused:
            remember(turn, self._history)

    async def _resume(self, turn: Turn, tts: TextToSpeech, remainder: Remainder) -> None:
        """Продолжение прерванного ответа с первого непроизнесённого предложения."""
        turn.resumed = True
        turn.style = resume_style(remainder)
        await remainder.wait(RESUME_WAIT_S)
        async with closing(remainder_sentences(turn, remainder)) as sentences:
            await self._speak(turn, tts, sentences)

    async def _speak(
        self, turn: Turn, tts: TextToSpeech, sentences: AsyncIterator[handoffs.Sentence]
    ) -> None:
        """Озвучивает предложения ответа; уступил результату — дочитывает остаток для продолжения."""
        reply = self._pauses.start(turn)
        try:
            await self._play(
                turn, speak_answer(turn, tts, sentences, functools.partial(self._is_live, turn), reply)
            )
        finally:
            self._pauses.stop(reply)
        if turn.paused:
            await reply.collect(sentences)

    async def _recover(self, turn: Turn) -> None:
        """После ошибки: сигнал ошибки и, если ответ ещё не начат, пустой ответ (reply_end)."""
        await self._error_tone(turn)
        if not turn.play_started:
            await self._play(turn, no_audio())

    async def _error_tone(self, turn: Turn) -> None:
        """Сигнал ошибки колонке — только если ход ещё актуален (прерванному не пищим)."""
        if self._is_live(turn):
            await self._devices.send_tone(turn.utterance.device_id, ERROR_TONE)

    async def _play(self, turn: Turn, audio: AsyncIterator[bytes]) -> None:
        """Отдаёт поток звука хабу в рамках хода; поток закрывается в любом случае."""
        turn.play_started = True
        async with closing(audio) as stream:
            await self._devices.play(turn.utterance.device_id, turn.utterance.turn, stream)

    async def _reply(self, turn: Turn, parts: Parts, messages: list[ChatMessage]) -> None:
        """Запускает исполнителя и проигрывает ответ.

        Первый кусок берём до play, напоминая колонке «думаю»: если исполнитель
        недоступен или молчит дольше first_part_limit_s — сигнал ошибки и пустой
        ответ. Генератор исполнителя закрывается при любом выходе, кроме отложенного
        ответа цели: тогда он у фоновой задачи.
        """
        turn.path = [handoffs.entry_id(parts.executor)]
        CALL_CONTEXT.set(CallContext(turn.person or None, turn.utterance.device_id))  # скиллам: кто и откуда
        async with closing(watched(parts.executor.run(messages)), keep=lambda: turn.deferred) as stream:
            try:
                first = await first_part(
                    stream,
                    functools.partial(self._thinking, turn),
                    self._thinking_interval_s,
                    self._first_part_limit_s,
                )
            except ExecutorError as error:
                _log.warning("Колонка %s: исполнитель не ответил: %s", turn.device_name, error)
                turn.failed = True
                await self._error_tone(turn)
                await self._play(turn, no_audio())
                return
            async with (
                closing(handoffs.collect(turn, first, stream, self._waiting(turn))) as texts,
                closing(handoffs.answer_sentences(texts)) as sentences,
            ):
                await self._speak(turn, parts.tts, sentences)
        settle(turn)  # сигнал ошибки — только если звука не было: оборванного ответа колонке достаточно
        if turn.failed and turn.first_audio_ms is None:
            await self._error_tone(turn)

    async def _thinking(self, turn: Turn) -> None:
        """Сигнал «думаю» колонке, пока ход актуален: продлевает её ожидание ответа."""
        if self._is_live(turn):
            await self._devices.send_tone(turn.utterance.device_id, THINKING_TONE)

    def _waiting(self, turn: Turn) -> handoffs.Waiting:
        """Как ждать куски ответа этого хода: «думаю», актуальность и пределы оркестратора."""
        return handoffs.Waiting(
            functools.partial(self._thinking, turn),
            functools.partial(self._is_live, turn),
            self._thinking_interval_s,
            self._part_idle_s,
            self._delegate_limit_s,
            defer=functools.partial(self._late.defer, turn),
        )
