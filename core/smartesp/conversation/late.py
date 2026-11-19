"""Запоздавшие ответы: цель передачи не уложилась в предел хода — ответ дожидается фоновая задача.

Ход к этому моменту уже закончился фразой «<Имя> долго думает…». Фоновая задача
дочитывает поток цели (пауза между кусками — part_idle_s, всего — late_limit_s от
начала хода), записывает ответ в историю и отдаёт его очереди объявлений. Не
дождались (сбой, пусто, предел) — событие «не доставлено», вслух ничего.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from smartesp.contracts import Announcer, ChatMessage, DevicePort, ExecutorError, Handoff, ReplyPart

from .history import History
from .sentences import clean_for_speech, strip_style_tag
from .streams import closing, drop, next_part
from .turn import Turn
from .turn_events import undelivered_data
from .turn_tasks import TurnTasks

_log = logging.getLogger(__name__)

LATE_LIMIT_S = 600.0  # дольше этого от начала хода запоздавший ответ не ждём
ANSWER_PREFIX = "{name} отвечает: "  # начало объявления запоздавшего ответа


@dataclass(frozen=True)
class _Job:
    """Что дождаться: ход, передача, начатое чтение первого куска цели и поток кусков."""

    turn: Turn
    handoff: Handoff
    pending: asyncio.Task[ReplyPart | None]
    parts: AsyncIterator[ReplyPart]
    announcer: Announcer


class LateAnswers:
    """Фоновые задачи запоздавших ответов и решение, брать ли поток цели."""

    def __init__(
        self,
        devices: DevicePort,
        history: History,
        publish: Callable[[str, dict[str, object]], None],
        part_idle_s: float,
        late_limit_s: float = LATE_LIMIT_S,
    ) -> None:
        """devices — колонки; history — куда записать ответ; publish — событие ленты.

        part_idle_s — предел паузы между кусками; late_limit_s — предел от начала хода (секунды).
        """
        self._devices = devices
        self._history = history
        self._publish = publish
        self._part_idle_s = part_idle_s
        self._late_limit_s = late_limit_s
        self._tasks = TurnTasks()
        self.proactive = True  # «Кузя может заговорить сам»: только для новых отложенных ответов
        self.accepting = True  # ядро останавливается — новых не берём
        self.announcer: Announcer | None = None

    def defer(
        self,
        turn: Turn,
        handoff: Handoff,
        pending: asyncio.Task[ReplyPart | None],
        parts: AsyncIterator[ReplyPart],
    ) -> bool:
        """Берёт поток цели фоновой задачей; True — взят (закрывать его вызывающему нельзя).

        False — речь по инициативе выключена, нет очереди объявлений, ядро
        останавливается или колонка хода её не умеет (протокол < 3).
        """
        announcer = self.announcer
        device_id = turn.utterance.device_id
        if not (self.proactive and self.accepting and announcer is not None):
            return False
        if not self._devices.supports_proactive(device_id):
            return False
        job = _Job(turn, handoff, pending, parts, announcer)
        self._tasks.start(self._wait(job), name=f"late answer {device_id}#{turn.utterance.turn}")
        return True

    async def cancel_all(self) -> None:
        """Отменяет все ожидания запоздавших ответов сразу (потоки цели закрываются) и ждёт их конца."""
        await self._tasks.cancel_all()

    async def _wait(self, job: _Job) -> None:
        """Дожидается ответа цели и отдаёт его очереди объявлений; не дождались — событие."""
        name = job.handoff.target_name
        remaining = job.turn.received_at + self._late_limit_s - time.monotonic()
        try:
            async with closing(job.parts) as parts:
                try:
                    async with asyncio.timeout(remaining):
                        text = await self._collect(job.pending, parts)
                finally:
                    await drop(job.pending)  # до закрытия генератора: чтение не должно идти
        except Exception as error:  # сбой, пусто или предел — одинаково: вслух ничего
            _log.warning("Колонка %s: ответ %s не получен: %r", job.turn.device_name, name, error)
            text = ""
        if not text:
            self._publish("turn_finished", undelivered_data(job.turn, job.handoff))
            return
        message = ANSWER_PREFIX.format(name=name) + text
        self._history.add_messages([ChatMessage("assistant", message)])
        job.announcer.say(job.turn.utterance.device_id, message, job.handoff.target)

    async def _collect(self, pending: asyncio.Task[ReplyPart | None], parts: AsyncIterator[ReplyPart]) -> str:
        """Весь текст ответа цели для озвучки; фраза сети об ошибке — ExecutorError.

        Каждая следующая передача начинает новый ответ (со своей меткой стиля).
        """
        answers: list[str] = [""]
        part = await pending
        while part is not None:
            if part.failure:
                raise ExecutorError(part.text)
            if part.handoff is not None:
                answers.append("")
            else:
                answers[-1] += part.text
            part = await next_part(parts, self._part_idle_s)
        texts = (clean_for_speech(strip_style_tag(answer)[1]) for answer in answers)
        return " ".join(text for text in texts if text)
