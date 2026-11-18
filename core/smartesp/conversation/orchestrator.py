"""Оркестратор хода: вопрос с колонки → STT → пометки → исполнитель → TTS → звук на колонку."""

import asyncio
import dataclasses
import functools
import logging
import time
from collections.abc import AsyncIterator

from smartesp.contracts import (
    Analyzer,
    ChatMessage,
    DevicePort,
    Executor,
    ExecutorError,
    ReplyPart,
    SpeechToText,
    TextToSpeech,
    Utterance,
)

from .history import History
from .prompt import build_messages
from .sentences import clean_for_speech, is_meaningless, split_sentences, take_style
from .streams import closing, first_part, next_part, no_audio
from .turn import Turn, answer_text, format_ms, status

_log = logging.getLogger(__name__)

ERROR_TONE = "error"  # сигнал колонке «ответить не получилось»
THINKING_TONE = "thinking"  # сигнал «думаю»: колонка продлевает ожидание ответа (у неё 15 с)
THINKING_INTERVAL_S = 8.0  # как часто слать «думаю», пока нет первого куска ответа
FIRST_PART_LIMIT_S = 45.0  # дольше первого куска не ждём: сигнал ошибки и пустой ответ
PART_IDLE_S = 20.0  # пауза исполнителя между кусками дольше этого — сбой посреди ответа


class Orchestrator:
    """Ведёт ходы разговора: на каждую реплику — своя задача."""

    def __init__(
        self,
        devices: DevicePort,
        stt: SpeechToText,
        analyze: Analyzer,
        executor: Executor,
        tts: TextToSpeech,
        history: History,
        *,
        thinking_interval_s: float = THINKING_INTERVAL_S,
        first_part_limit_s: float = FIRST_PART_LIMIT_S,
        part_idle_s: float = PART_IDLE_S,
    ) -> None:
        """Запоминает колонки, распознавание, обработчики, исполнителя, синтез и историю.

        thinking_interval_s — период сигнала «думаю», пока ждём первый кусок ответа;
        first_part_limit_s — сколько всего ждать первый кусок; part_idle_s — сколько
        ждать каждый следующий кусок. Всё в секундах.
        """
        self._devices = devices
        self._stt = stt
        self._analyze = analyze
        self._executor = executor
        self._tts = tts
        self._history = history
        self._thinking_interval_s = thinking_interval_s
        self._first_part_limit_s = first_part_limit_s
        self._part_idle_s = part_idle_s
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        """Бесконечно ждёт реплики и запускает на каждую свою задачу хода.

        Ошибка хода пишется в журнал и не останавливает run. При отмене run
        отменяет и дожидается незавершённых ходов.
        """
        try:
            while True:
                utterance = await self._devices.next_utterance()
                task = asyncio.create_task(
                    self._handle(utterance, time.monotonic()),
                    name=f"turn {utterance.device_id}#{utterance.turn}",
                )
                self._tasks.add(task)
                task.add_done_callback(self._on_turn_done)
        finally:
            await self._cancel_turns()

    def _on_turn_done(self, task: asyncio.Task[None]) -> None:
        """Забывает задачу хода и пишет в журнал её ошибку, если была."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _log.error("Ход %s упал", task.get_name(), exc_info=error)

    async def _cancel_turns(self) -> None:
        """Отменяет незавершённые ходы и ждёт их завершения."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _is_live(self, turn: Turn) -> bool:
        """True, пока ход актуален для колонки."""
        return self._devices.is_active(turn.utterance.device_id, turn.utterance.turn)

    async def _handle(self, utterance: Utterance, received_at: float) -> None:
        """Один ход целиком; любая ошибка (кроме отмены) — сигнал ошибки, колонка не молчит."""
        turn = Turn(utterance, self._devices.device_name(utterance.device_id), received_at)
        try:
            await self._converse(turn)
        except Exception:
            _log.error("Колонка %s: ход %s упал", turn.device_name, utterance.turn, exc_info=True)
            turn.failed = True
            await self._recover(turn)
        self._log_turn(turn)

    async def _converse(self, turn: Turn) -> None:
        """Распознаёт, понимает, отвечает и записывает завершённый ход в историю."""
        turn.text = await self._stt.transcribe(turn.utterance.pcm)
        turn.stt_ms = turn.elapsed_ms()
        if is_meaningless(turn.text):
            turn.meaningless = True
            await self._play(turn, no_audio())
            return
        if not self._is_live(turn):
            return
        turn.annotations = await self._analyze(dataclasses.replace(turn.utterance, text=turn.text))
        messages = build_messages(turn.annotations, self._history.messages(), turn.text, turn.device_name)
        await self._reply(turn, messages)
        answer = answer_text(turn)
        if turn.completed and answer and self._is_live(turn):
            self._history.add(turn.text, answer)

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

    async def _reply(self, turn: Turn, messages: list[ChatMessage]) -> None:
        """Запускает исполнителя и проигрывает ответ.

        Первый кусок берём до play, напоминая колонке «думаю»: если исполнитель
        недоступен или молчит дольше first_part_limit_s — сигнал ошибки и пустой
        ответ. Генератор исполнителя закрывается при любом выходе.
        """
        async with closing(self._executor.run(messages)) as parts:
            try:
                first = await first_part(
                    parts,
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
            if first is not None:
                turn.first_text_ms = turn.elapsed_ms()
            async with (
                closing(self._collect(turn, first, parts)) as texts,
                closing(split_sentences(texts)) as sentences,
            ):
                await self._play(turn, self._speak(turn, sentences))
        await self._finish_reply(turn)

    async def _finish_reply(self, turn: Turn) -> None:
        """Итог проигранного ответа.

        Пустой ответ модели — сбой. Сигнал ошибки — только если звука не было:
        оборванного на полуслове ответа колонке достаточно.
        """
        if turn.completed and not answer_text(turn):
            _log.warning("Колонка %s: модель вернула пустой ответ", turn.device_name)
            turn.completed = False
            turn.failed = True
        if turn.failed and turn.first_audio_ms is None:
            await self._error_tone(turn)

    async def _thinking(self, turn: Turn) -> None:
        """Сигнал «думаю» колонке, пока ход актуален: продлевает её ожидание ответа."""
        if self._is_live(turn):
            await self._devices.send_tone(turn.utterance.device_id, THINKING_TONE)

    async def _collect(
        self, turn: Turn, first: ReplyPart | None, parts: AsyncIterator[ReplyPart]
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт заранее взятый первый кусок и остальные; копит текст ответа.

        Исполнитель молчит между кусками дольше part_idle_s — ExecutorError.
        """
        part = first
        while part is not None:
            turn.answer.append(part.text)
            yield part
            part = await next_part(parts, self._part_idle_s)

    async def _speak(self, turn: Turn, sentences: AsyncIterator[str]) -> AsyncIterator[bytes]:
        """Озвучивает предложения по одному и отдаёт PCM; останавливается, как только ход неактуален.

        Ошибка исполнителя или TTS посреди ответа заканчивает поток штатно
        (колонка получит reply_end, а не застрянет в «говорю») и помечает ход
        как упавший; сигнал ошибки (если звука не было) шлёт _finish_reply.
        """
        first = True
        try:
            async for sentence in sentences:
                if not self._is_live(turn):
                    return
                if first:  # метка стиля — только в начале ответа
                    turn.style, sentence = take_style(sentence, self._tts.styles())
                    first = False
                text = clean_for_speech(sentence)
                if not text:
                    continue
                async with closing(self._tts.synthesize(text, turn.style)) as audio:
                    async for chunk in audio:
                        if not self._is_live(turn):
                            return
                        if turn.first_audio_ms is None:
                            turn.first_audio_ms = turn.elapsed_ms()
                        yield chunk
        except ExecutorError as error:
            _log.warning("Колонка %s: исполнитель упал посреди ответа: %s", turn.device_name, error)
            turn.failed = True
            return
        except Exception:
            _log.error("Колонка %s: ошибка посреди ответа", turn.device_name, exc_info=True)
            turn.failed = True
            return
        turn.completed = self._is_live(turn)

    def _log_turn(self, turn: Turn) -> None:
        """Пишет в журнал итог хода: вопрос, пометки, задержки и ответ."""
        _log.info(
            "Колонка %s: ход %s; вопрос %r; пометки %s; стиль %s; "
            "stt_ms=%s first_text_ms=%s first_audio_ms=%s; ответ %r",
            turn.device_name,
            status(turn),
            turn.text,
            [f"[{a.source}] {a.text}" for a in turn.annotations],
            turn.style,
            format_ms(turn.stt_ms),
            format_ms(turn.first_text_ms),
            format_ms(turn.first_audio_ms),
            answer_text(turn),
        )
