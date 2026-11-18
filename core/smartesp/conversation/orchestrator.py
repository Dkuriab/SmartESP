"""Оркестратор хода: вопрос с колонки → STT → пометки → исполнитель → TTS → звук на колонку."""

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from smartesp.contracts import (
    Analyzer,
    Annotation,
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
from .sentences import clean_for_speech, is_meaningless, split_sentences

_log = logging.getLogger(__name__)

SPEECH_STYLE = "normal"  # стиль озвучки (выбор стиля моделью — позже)
ERROR_TONE = "error"  # сигнал колонке «исполнитель недоступен»


@asynccontextmanager
async def _closing[T](iterator: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    """Как contextlib.aclosing, но для любого AsyncIterator: закрывает его, если это генератор."""
    try:
        yield iterator
    finally:
        if isinstance(iterator, AsyncGenerator):
            await iterator.aclose()


async def _no_audio() -> AsyncIterator[bytes]:
    """Пустой поток звука: хаб пошлёт reply_start + reply_end, колонка перестанет ждать."""
    for chunk in list[bytes]():
        yield chunk


@dataclass
class _Turn:
    """Состояние одного хода и замеры задержек (мс от прихода реплики в оркестратор)."""

    utterance: Utterance
    device_name: str
    received_at: float
    text: str = ""
    annotations: list[Annotation] = field(default_factory=list[Annotation])
    answer: list[str] = field(default_factory=list[str])
    stt_ms: float | None = None
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    completed: bool = False  # ответ отдан целиком, ход ещё актуален
    failed: bool = False  # исполнитель упал

    def elapsed_ms(self) -> float:
        """Сколько миллисекунд прошло с прихода реплики."""
        return (time.monotonic() - self.received_at) * 1000


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
    ) -> None:
        """Запоминает колонки, распознавание, обработчики, исполнителя, синтез и историю."""
        self._devices = devices
        self._stt = stt
        self._analyze = analyze
        self._executor = executor
        self._tts = tts
        self._history = history
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

    def _is_live(self, turn: _Turn) -> bool:
        """True, пока ход актуален для колонки."""
        return self._devices.is_active(turn.utterance.device_id, turn.utterance.turn)

    async def _handle(self, utterance: Utterance, received_at: float) -> None:
        """Один ход целиком: распознать, понять, ответить, записать в историю и журнал."""
        turn = _Turn(utterance, self._devices.device_name(utterance.device_id), received_at)
        turn.text = await self._stt.transcribe(utterance.pcm)
        turn.stt_ms = turn.elapsed_ms()
        if is_meaningless(turn.text):
            _log.info("Колонка %s: бессмысленный текст %r — пустой ответ", turn.device_name, turn.text)
            await self._play(turn, _no_audio())
            return
        if not self._is_live(turn):
            _log.info("Колонка %s: ход прерван до ответа (%r)", turn.device_name, turn.text)
            return
        turn.annotations = await self._analyze(dataclasses.replace(utterance, text=turn.text))
        messages = build_messages(turn.annotations, self._history.messages(), turn.text, turn.device_name)
        await self._reply(turn, messages)
        answer = "".join(turn.answer).strip()
        if turn.completed and answer and self._is_live(turn):
            self._history.add(turn.text, answer)
        self._log_turn(turn, answer)

    async def _play(self, turn: _Turn, audio: AsyncIterator[bytes]) -> None:
        """Отдаёт поток звука хабу в рамках хода; поток закрывается в любом случае."""
        async with _closing(audio) as stream:
            await self._devices.play(turn.utterance.device_id, turn.utterance.turn, stream)

    async def _reply(self, turn: _Turn, messages: list[ChatMessage]) -> None:
        """Запускает исполнителя и проигрывает ответ.

        Первый кусок берём до play: если исполнитель недоступен — сигнал ошибки
        и пустой ответ. Генератор исполнителя закрывается при любом выходе.
        """
        async with _closing(self._executor.run(messages)) as parts:
            try:
                first = await anext(parts, None)
            except ExecutorError as error:
                _log.warning("Колонка %s: исполнитель недоступен: %s", turn.device_name, error)
                turn.failed = True
                await self._devices.send_tone(turn.utterance.device_id, ERROR_TONE)
                await self._play(turn, _no_audio())
                return
            turn.first_text_ms = turn.elapsed_ms()
            async with (
                _closing(self._collect(turn, first, parts)) as texts,
                _closing(split_sentences(texts)) as sentences,
            ):
                await self._play(turn, self._speak(turn, sentences))
        if turn.failed:
            await self._devices.send_tone(turn.utterance.device_id, ERROR_TONE)

    async def _collect(
        self, turn: _Turn, first: ReplyPart | None, parts: AsyncIterator[ReplyPart]
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт заранее взятый первый кусок и остальные; копит текст ответа."""
        if first is None:
            return
        turn.answer.append(first.text)
        yield first
        async for part in parts:
            turn.answer.append(part.text)
            yield part

    async def _speak(self, turn: _Turn, sentences: AsyncIterator[str]) -> AsyncIterator[bytes]:
        """Озвучивает предложения по одному и отдаёт PCM; останавливается, как только ход неактуален.

        Ошибка исполнителя посреди ответа заканчивает поток (колонка получит
        reply_end) и помечает ход как упавший.
        """
        try:
            async for sentence in sentences:
                if not self._is_live(turn):
                    return
                text = clean_for_speech(sentence)
                if not text:
                    continue
                async with _closing(self._tts.synthesize(text, SPEECH_STYLE)) as audio:
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
        turn.completed = self._is_live(turn)

    def _log_turn(self, turn: _Turn, answer: str) -> None:
        """Пишет в журнал итог хода: вопрос, пометки, задержки и ответ."""
        status = "ошибка" if turn.failed else ("готов" if turn.completed else "прерван")
        _log.info(
            "Колонка %s: ход %s; вопрос %r; пометки %s; "
            "stt_ms=%s first_text_ms=%s first_audio_ms=%s; ответ %r",
            turn.device_name,
            status,
            turn.text,
            [f"[{a.source}] {a.text}" for a in turn.annotations],
            _ms(turn.stt_ms),
            _ms(turn.first_text_ms),
            _ms(turn.first_audio_ms),
            answer,
        )


def _ms(value: float | None) -> str:
    """Задержка для журнала: целые миллисекунды или «—», если до этого этапа не дошли."""
    return "—" if value is None else str(round(value))
