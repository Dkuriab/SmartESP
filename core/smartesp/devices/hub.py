"""Хаб колонок: сессии, арбитраж слов пробуждения, сбор вопросов, отправка ответов."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable
from typing import Any

from smartesp.contracts import Utterance

from .arbiter import Arbiter, Decision
from .connection import DeviceConnection
from .messages import BargeIn, Hello, PlaybackDone, UtteranceEnd, Wake, cancel_turn, parse_message, tone
from .playback import send_reply
from .session import ActiveTurn, Recording, Session

POLL_S = 0.05  # как часто таймер хаба спрашивает арбитра
NO_SPEECH = "no_speech"

logger = logging.getLogger(__name__)


class DeviceHub:
    """Все подключённые колонки. Реализует DevicePort из contracts.

    Номер хода (Utterance.turn и аргумент turn в is_active/play) — номер хода в хабе:
    уникален на всё время жизни хаба, выдаётся при принятии хода (1, 2, 3…). Номера
    колонки (ESP) после перезагрузки снова начинаются с 1, поэтому наружу не выдаются;
    хаб переводит свой номер в номер колонки только в кадрах reply_start/reply_end/
    cancel_turn. Ход заменённой или отключённой сессии больше никогда не активен.
    """

    def __init__(
        self,
        window_s: float,
        late_s: float,
        names: dict[str, str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """window_s, late_s — окна арбитра; names — имена колонок по id; clock — часы (секунды)."""
        self._arbiter = Arbiter(window_s, late_s)
        self._names = dict(names)
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self._poll_task: asyncio.Task[None] | None = None
        self._turn_ids = itertools.count(1)
        self._background: set[asyncio.Task[object]] = set()  # отправки, которых никто не ждёт

    async def handle(self, conn: DeviceConnection) -> None:
        """Обслуживает одно соединение, пока колонка подключена. Обрыв связи — не ошибка."""
        self._ensure_polling()
        session: Session | None = None
        try:
            session = await self._wait_hello(conn)
            self._open(session)
            while not session.closed:
                self._on_frame(session, await conn.receive())
        except ConnectionError:
            pass
        finally:
            if session is not None:
                self._close(session)

    async def next_utterance(self) -> Utterance:
        """Ждёт следующий принятый вопрос от любой колонки."""
        return await self._utterances.get()

    def is_active(self, device_id: str, turn: int) -> bool:
        """True, пока ход хаба turn принят и не закончен (нет barge_in, отмены, отключения, нового хода)."""
        session = self._sessions.get(device_id)
        return session is not None and session.is_live(turn)

    async def play(self, device_id: str, turn: int, audio: AsyncIterator[bytes]) -> None:
        """Шлёт ответ хода хаба turn с темпом. Ход не активен или связь оборвалась — тихо выходит."""
        session = self._sessions.get(device_id)
        if session is not None:
            await send_reply(session, turn, audio, self._clock)

    async def send_tone(self, device_id: str, name: str) -> None:
        """Просит колонку сыграть сигнал name; нет колонки или связи — ничего не делает."""
        session = self._sessions.get(device_id)
        if session is not None:
            await session.send(tone(name))

    def device_name(self, device_id: str) -> str:
        """Имя колонки из конфигурации или сам id."""
        return self._names.get(device_id, device_id)

    async def aclose(self) -> None:
        """Останавливает таймер арбитра и фоновые отправки и ждёт их. Повторный вызов безопасен."""
        tasks = [t for t in (self._poll_task, *self._background) if t is not None]
        self._poll_task = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- сессии ---

    def _ensure_polling(self) -> None:
        """Запускает таймер арбитра при первом подключении (живёт, пока жив хаб)."""
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Раз в POLL_S закрывает истёкшие окна арбитража и применяет решения."""
        while True:
            await asyncio.sleep(POLL_S)
            try:
                self._apply(self._arbiter.poll(self._clock()))
            except Exception:  # таймер не должен умирать от одной ошибки
                logger.exception("arbiter poll failed")

    def _spawn(self, coro: Coroutine[Any, Any, object], what: str) -> None:
        """Запускает отправку в фоне: зависшая колонка не должна тормозить хаб и других."""
        task = asyncio.create_task(coro)
        self._background.add(task)

        def done(t: asyncio.Task[object]) -> None:
            self._background.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("%s failed", what, exc_info=t.exception())

        task.add_done_callback(done)

    async def _wait_hello(self, conn: DeviceConnection) -> Session:
        """Ждёт hello; всё, что пришло раньше, игнорирует."""
        while True:
            frame = await conn.receive()
            message = parse_message(frame) if isinstance(frame, str) else None
            if isinstance(message, Hello):
                return Session(message.device_id or f"legacy:{conn.remote}", conn)

    def _open(self, session: Session) -> None:
        """Регистрирует сессию; прежняя сессия с тем же id закрывается (в фоне)."""
        old = self._sessions.get(session.device_id)
        self._sessions[session.device_id] = session
        logger.info("device %s connected from %s", session.device_id, session.conn.remote)
        if old is not None:
            self._end_session(old)
            self._spawn(_close_quietly(old.conn), f"closing old session of {old.device_id}")

    def _close(self, session: Session) -> None:
        """Колонка отключилась: убрать сессию (если её не заменили) и закончить ход."""
        if self._sessions.get(session.device_id) is session:
            del self._sessions[session.device_id]
            logger.info("device %s disconnected", session.device_id)
        self._end_session(session)

    def _end_session(self, session: Session) -> None:
        """Помечает сессию закрытой, выбрасывает запись и заканчивает активный ход."""
        session.closed = True
        session.recording = None
        if session.active is not None:
            self._end_turn(session, session.active.esp_turn)

    def _end_turn(self, session: Session, esp_turn: int) -> None:
        """Заканчивает активный ход колонки esp_turn (если он активен) и сообщает арбитру."""
        if session.active is not None and session.active.esp_turn == esp_turn:
            session.active = None
            self._arbiter.on_turn_finished(session.device_id, esp_turn)

    # --- входящие кадры ---

    def _on_frame(self, session: Session, frame: str | bytes) -> None:
        """Разбирает кадр колонки: звук вопроса или сообщение протокола."""
        if isinstance(frame, bytes):
            recording = session.recording
            if recording is not None and not recording.ended:
                recording.pcm += frame
            return
        message = parse_message(frame)
        if isinstance(message, Wake):
            self._on_wake(session, message)
        elif isinstance(message, UtteranceEnd):
            self._on_utterance_end(session, message)
        elif isinstance(message, BargeIn | PlaybackDone):
            self._end_turn(session, message.turn)

    def _on_wake(self, session: Session, wake: Wake) -> None:
        """Новый ход: прежний заканчивается, звук копится, решает арбитр."""
        if session.active is not None:
            self._end_turn(session, session.active.esp_turn)
        now = self._clock()
        session.recording = Recording(esp_turn=wake.turn, started_at=now)
        self._apply(self._arbiter.on_wake(session.device_id, wake.turn, wake.level, now))

    def _on_utterance_end(self, session: Session, end: UtteranceEnd) -> None:
        """Конец вопроса: без речи — выбросить; принятый ход — отдать в очередь."""
        recording = session.recording
        if recording is None or recording.esp_turn != end.turn or recording.ended:
            return
        if end.reason == NO_SPEECH:
            session.recording = None
            self._end_turn(session, end.turn)
            return
        recording.ended = True
        if recording.turn_id is not None:
            self._emit(session, recording, recording.turn_id)

    def _emit(self, session: Session, recording: Recording, turn_id: int) -> None:
        """Готовый вопрос принятого хода → очередь Utterance (turn — номер хода в хабе)."""
        session.recording = None
        pcm = bytes(recording.pcm)
        self._utterances.put_nowait(Utterance(session.device_id, turn_id, pcm, recording.started_at))

    # --- решения арбитра ---

    def _apply(self, decisions: Iterable[Decision]) -> None:
        """Применяет решения арбитра по порядку. Сам ничего не ждёт: отправки — в фоне."""
        for decision in decisions:
            if decision.kind == "accept":
                self._accept(decision)
            else:
                self._cancel(decision)

    def _accept(self, decision: Decision) -> None:
        """Ход принят: он становится активным; если вопрос уже закончен — в очередь."""
        session = self._sessions.get(decision.device_id)
        recording = session.recording if session is not None else None
        if session is None or recording is None or recording.esp_turn != decision.turn:
            # колонка ушла или уже начала другой ход — принимать нечего
            self._arbiter.on_turn_finished(decision.device_id, decision.turn)
            return
        recording.turn_id = next(self._turn_ids)
        session.active = ActiveTurn(turn_id=recording.turn_id, esp_turn=decision.turn)
        if recording.ended:
            self._emit(session, recording, recording.turn_id)

    def _cancel(self, decision: Decision) -> None:
        """Ход отменён: выбросить запись, закончить ход, сказать колонке cancel_turn."""
        self._arbiter.on_turn_finished(decision.device_id, decision.turn)
        session = self._sessions.get(decision.device_id)
        if session is None:
            return
        if session.recording is not None and session.recording.esp_turn == decision.turn:
            session.recording = None
        self._end_turn(session, decision.turn)
        self._spawn(session.send(cancel_turn(decision.turn)), f"cancel_turn to {session.device_id}")


async def _close_quietly(conn: DeviceConnection) -> None:
    """Закрывает соединение; уже оборванное — не ошибка."""
    try:
        await conn.close()
    except ConnectionError:
        pass
