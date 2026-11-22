"""Хаб колонок: сессии, арбитраж слов пробуждения, сбор вопросов, отправка ответов."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterable

from smartesp.contracts import DeviceInfo, EventSink, Utterance

from .arbiter import Arbiter, Decision
from .connection import DeviceConnection, close_quietly
from .messages import (
    BargeIn,
    Busy,
    PlaybackDone,
    Played,
    UpdateStatus,
    UtteranceEnd,
    Wake,
    cancel_turn,
    parse_message,
    tone,
)
from .playback import send_reply
from .proactive import REPLY_GRACE_S, CoreTurns
from .registry import DeviceRegistry
from .session import ActiveTurn, Recording, Session, wait_hello

POLL_S = 0.05  # как часто таймер хаба спрашивает арбитра
NO_SPEECH = "no_speech"

logger = logging.getLogger(__name__)


class DeviceHub(CoreTurns):
    """Все подключённые колонки. Реализует DevicePort из contracts (ходы ядра — в CoreTurns).

    Номер хода (Utterance.turn и аргумент turn в is_active/play) — номер хода в хабе:
    уникален на всё время жизни хаба, выдаётся при принятии хода (1, 2, 3…). Номера
    колонки (ESP) после перезагрузки снова начинаются с 1, поэтому наружу не выдаются;
    хаб переводит свой номер в номер колонки только в кадрах reply_start/reply_end/
    cancel_turn. Ходы ядра (announce, listen) колонка получает с номером 0x80000000 | n.
    Ход заменённой или отключённой сессии больше никогда не активен.
    """

    def __init__(
        self,
        window_s: float,
        late_s: float,
        names: dict[str, str],
        clock: Callable[[], float] = time.monotonic,
        *,
        events: EventSink | None = None,
        wall_clock: Callable[[], float] = time.time,
        reply_grace_s: float = REPLY_GRACE_S,
    ) -> None:
        """window_s, late_s — окна арбитра; names — имена колонок по id; clock — часы (секунды).

        events — приёмник событий (None — без событий); wall_clock — настенные часы для last_seen;
        reply_grace_s — запас сверх длительности объявления на ожидание playback_done.
        """
        super().__init__(Arbiter(window_s, late_s), clock, reply_grace_s)
        self._registry = DeviceRegistry(names)
        self._events = events
        self._wall_clock = wall_clock
        self._utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self._poll_task: asyncio.Task[None] | None = None

    async def handle(self, conn: DeviceConnection) -> None:
        """Обслуживает одно соединение, пока колонка подключена. Обрыв связи — не ошибка."""
        self._ensure_polling()
        session: Session | None = None
        try:
            session, fw = await wait_hello(conn)
            self._open(session, fw)
            while not session.closed:
                frame = await conn.receive()
                self._registry.touch(session.device_id, self._wall_clock())
                self._on_frame(session, frame)
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
        return self._registry.name(device_id)

    def set_names(self, names: dict[str, str]) -> None:
        """Заменяет имена колонок на лету."""
        self._registry.set_names(names)

    def devices(self) -> list[DeviceInfo]:
        """Подключённые и известные по настройкам колонки, по имени."""
        return self._with_state(self._registry.devices(set(self._sessions)))

    def stop_accepting(self) -> None:
        """Новые вопросы не принимаются, звучащие ответы доигрываются.

        Новые и ожидающие решения арбитра wake отменяются (cancel_turn), запись выбрасывается;
        уже принятые ходы идут дальше, их вопрос ещё может попасть в next_utterance.
        """
        self._accepting = False
        for session in list(self._sessions.values()):
            pending = session.recording
            if pending is not None and pending.turn_id is None:
                session.recording = None
                self._send_cancel(session, pending.esp_turn)

    async def close_all(self) -> None:
        """Закрывает все соединения и сразу заканчивает их сессии."""
        sessions = list(self._sessions.values())
        await asyncio.gather(*(close_quietly(s.conn) for s in sessions))
        for session in sessions:
            self._close(session)

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

    def _send_cancel(self, session: Session, esp_turn: int) -> None:
        """Шлёт cancel_turn в фоне и сообщает арбитру, что ход закончен."""
        self._arbiter.on_turn_finished(session.device_id, esp_turn)
        self._spawn(session.send(cancel_turn(esp_turn)), f"cancel_turn to {session.device_id}")

    def _publish(self, kind: str, data: dict[str, object]) -> None:
        """Публикует событие, если есть приёмник."""
        if self._events is not None:
            self._events.publish(kind, data)

    def _open(self, session: Session, fw: str) -> None:
        """Регистрирует сессию; прежняя сессия с тем же id закрывается (в фоне)."""
        old = self._sessions.get(session.device_id)
        self._sessions[session.device_id] = session
        remote = session.conn.remote
        self._registry.hello(session.device_id, remote, fw, session.protocol, self._wall_clock())
        logger.info("device %s connected from %s", session.device_id, remote)
        info = {"device_id": session.device_id, "name": self.device_name(session.device_id)}
        self._publish("device_connected", {**info, "remote": remote, "fw": fw, "protocol": session.protocol})
        self._send_volume(session)
        if old is not None:
            self._end_session(old)
            self._spawn(close_quietly(old.conn), f"closing old session of {old.device_id}")

    def _close(self, session: Session) -> None:
        """Колонка отключилась: убрать сессию (если её не заменили) и закончить ход."""
        if self._sessions.get(session.device_id) is session:
            del self._sessions[session.device_id]
            logger.info("device %s disconnected", session.device_id)
            self._publish("device_disconnected", {"device_id": session.device_id})
        self._end_session(session)

    def _end_session(self, session: Session) -> None:
        """Помечает сессию закрытой, выбрасывает запись и заканчивает активный ход."""
        session.closed = True
        session.recording = None
        if session.active is not None:
            self._end_turn(session, session.active.esp_turn, "lost")

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
        elif isinstance(message, BargeIn):
            self._end_turn(session, message.turn, "interrupted")
        elif isinstance(message, PlaybackDone):
            self._end_turn(session, message.turn, "delivered")
        elif isinstance(message, Busy):
            self._on_busy(session, message.turn)
        elif isinstance(message, Played):
            self._on_played(session, message)
        elif isinstance(message, UpdateStatus):
            self._updates.apply(session.device_id, message)

    def _on_wake(self, session: Session, wake: Wake) -> None:
        """Новый ход: прежний заканчивается, звук копится, решает арбитр. При остановке — сразу отмена."""
        if not self._accepting:
            self._send_cancel(session, wake.turn)
            return
        if session.active is not None:  # без barge_in: прежний ход колонка не играла (ход ядра — повторить)
            self._end_turn(session, session.active.esp_turn, "busy")
        self._publish("wake", {"device_id": session.device_id, "level": wake.level})
        now = self._clock()
        session.recording = Recording(esp_turn=wake.turn, started_at=now)
        self._apply(self._arbiter.on_wake(session.device_id, wake.turn, wake.level, now))

    def _on_utterance_end(self, session: Session, end: UtteranceEnd) -> None:
        """Конец вопроса: без речи — выбросить; принятый ход — отдать в очередь."""
        recording = session.recording
        if recording is None or recording.esp_turn != end.turn or recording.ended:
            return
        if end.reason == NO_SPEECH:
            self._captured(session, recording, b"")  # запись для обучения: речи не было
            session.recording = None
            self._end_turn(session, end.turn, "lost")
            return
        recording.ended = True
        if recording.turn_id is not None:
            self._emit(session, recording, recording.turn_id)

    def _emit(self, session: Session, recording: Recording, turn_id: int) -> None:
        """Готовый вопрос принятого хода → очередь Utterance (turn — номер хода в хабе)."""
        session.recording = None
        pcm = bytes(recording.pcm)
        if self._captured(session, recording, pcm):
            return
        utterance = Utterance(session.device_id, turn_id, pcm, recording.started_at, origin=recording.origin)
        self._utterances.put_nowait(utterance)

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
        self._publish("arbitration", {"device_id": decision.device_id, "decision": "accept"})
        recording.turn_id = next(self._turn_ids)
        session.active = ActiveTurn(turn_id=recording.turn_id, esp_turn=decision.turn)
        self._last_active = decision.device_id
        if recording.ended:
            self._emit(session, recording, recording.turn_id)

    def _cancel(self, decision: Decision) -> None:
        """Ход отменён: выбросить запись, закончить ход, сказать колонке cancel_turn."""
        self._publish("arbitration", {"device_id": decision.device_id, "decision": "cancel"})
        session = self._sessions.get(decision.device_id)
        if session is None:
            self._arbiter.on_turn_finished(decision.device_id, decision.turn)
            return
        if session.recording is not None and session.recording.esp_turn == decision.turn:
            session.recording = None
        self._end_turn(session, decision.turn, "interrupted")
        self._send_cancel(session, decision.turn)
