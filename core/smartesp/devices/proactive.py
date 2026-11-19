"""Ходы ядра поверх сессий: объявление и прослушивание (протокол 3) и итог доставки."""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator, Callable

from smartesp.contracts import Delivery

from .arbiter import Arbiter
from .messages import announce as announce_frame
from .messages import cancel_turn, tone
from .messages import listen as listen_frame
from .playback import close_audio, send_reply
from .session import ActiveTurn, Recording, Session

PROACTIVE_PROTOCOL = 3  # с этой версии колонка понимает listen и отвечает busy
REPLY_GRACE_S = 15.0  # нет playback_done за длительность звука + столько секунд — объявление потеряно
LISTEN_WAIT_S = 30.0  # сколько ждать playback_done хода перед listen
ATTENTION_TONE = "attention"  # сигнал перед речью по инициативе
LISTEN_ORIGIN = "listen"  # Utterance.origin хода, начатого командой listen

logger = logging.getLogger(__name__)


class CoreTurns:
    """Основа DeviceHub: сессии, номера ходов хаба и ходы, которые начинает ядро.

    Ход объявления в арбитраже не участвует: слово на другой колонке его не обрывает.
    Ход прослушивания арбитр не решает, но учитывает: новый ход другой колонки его отменит.
    Итог хода (Delivery) — ожидание в Session; его задаёт _end_turn.
    """

    def __init__(self, arbiter: Arbiter, clock: Callable[[], float], reply_grace_s: float) -> None:
        """arbiter — арбитр слов; clock — часы (секунды); reply_grace_s — запас ожидания playback_done."""
        self._arbiter = arbiter
        self._clock = clock
        self._reply_grace_s = reply_grace_s
        self._accepting = True
        self._sessions: dict[str, Session] = {}
        self._turn_ids = itertools.count(1)
        self._last_active: str | None = None

    def supports_proactive(self, device_id: str) -> bool:
        """True, если колонка подключена и её протокол ≥ 3."""
        session = self._sessions.get(device_id)
        return session is not None and session.protocol >= PROACTIVE_PROTOCOL

    def last_active_device(self) -> str | None:
        """Колонка последнего принятого хода (по слову или прослушиванию), если подключена."""
        return self._last_active if self._last_active in self._sessions else None

    async def announce(self, device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        """announce → tone attention → reply_start → звук → reply_end новым ходом ядра; ждёт итог.

        Колонка не подключена или протокол < 3 — "lost" без кадров; у хаба на ней идёт ход — "busy".
        Поток audio закрывается при любом выходе.
        """
        session = self._idle_session(device_id)
        if session is None:
            await close_audio(audio)
            return "busy" if self.supports_proactive(device_id) else "lost"
        turn_id, esp_turn = next(self._turn_ids), session.next_core_turn()
        session.active = ActiveTurn(turn_id, esp_turn)
        outcome = session.outcome(turn_id)
        assert outcome is not None  # ход только что стал активным
        sending = asyncio.create_task(self._send_announcement(session, turn_id, esp_turn, audio))
        try:
            await asyncio.wait((sending, outcome), return_when=asyncio.FIRST_COMPLETED)
        finally:
            sending.cancel()  # итог уже известен (busy, обрыв…) — дальше звук не нужен
            (sent,) = await asyncio.gather(sending, return_exceptions=True)
        if outcome.done():
            return outcome.result()
        if isinstance(sent, BaseException):
            logger.warning("announcement audio for %s failed", device_id, exc_info=sent)
            return await self._give_up(session, esp_turn, outcome)
        try:
            return await asyncio.wait_for(asyncio.shield(outcome), sent + self._reply_grace_s)
        except TimeoutError:
            return await self._give_up(session, esp_turn, outcome)

    async def listen(self, device_id: str) -> bool:
        """Шлёт listen свободной колонке v3 новым ходом ядра; True — команда ушла.

        Ход хаба выдаётся сразу, без арбитра; реплика придёт в next_utterance с origin "listen".
        Ответ busy потом снимет ход и выбросит запись.
        """
        session = self._idle_session(device_id)
        if session is None or not self._accepting:
            return False
        turn_id, esp_turn = next(self._turn_ids), session.next_core_turn()
        session.recording = Recording(esp_turn, self._clock(), turn_id=turn_id, origin=LISTEN_ORIGIN)
        session.active = ActiveTurn(turn_id, esp_turn)
        self._arbiter.on_turn_started(device_id, esp_turn)
        self._last_active = device_id
        return await session.send(listen_frame(esp_turn), turn_id)

    async def listen_after(self, device_id: str, turn: int) -> None:
        """Ждёт playback_done хода хаба turn (не дольше LISTEN_WAIT_S), затем listen.

        Ход кончился иначе (перебили, отменили, busy, обрыв), колонка v2 или переподключилась —
        ничего не делает.
        """
        session = self._sessions.get(device_id) if self.supports_proactive(device_id) else None
        outcome = session.outcome(turn) if session is not None else None
        if outcome is None:
            return
        try:
            result = await asyncio.wait_for(asyncio.shield(outcome), LISTEN_WAIT_S)
        except TimeoutError:
            return
        if result == "delivered" and self._sessions.get(device_id) is session:
            await self.listen(device_id)

    def _idle_session(self, device_id: str) -> Session | None:
        """Сессия колонки v3, на которой у хаба нет ни записи, ни хода; иначе None."""
        session = self._sessions.get(device_id) if self.supports_proactive(device_id) else None
        return session if session is not None and session.is_idle() else None

    async def _send_announcement(
        self, session: Session, turn_id: int, esp_turn: int, audio: AsyncIterator[bytes]
    ) -> float:
        """Кадры объявления по порядку; возвращает секунды отправленного звука."""
        try:
            if await session.send(announce_frame(esp_turn), turn_id) and await session.send(
                tone(ATTENTION_TONE), turn_id
            ):
                return await send_reply(session, turn_id, audio, self._clock)
            return 0.0
        finally:
            await close_audio(audio)

    async def _give_up(self, session: Session, esp_turn: int, outcome: asyncio.Future[Delivery]) -> Delivery:
        """Объявление не доиграно: ход потерян, колонку просим вернуться в покой (cancel_turn)."""
        if self._end_turn(session, esp_turn, "lost"):
            await session.send(cancel_turn(esp_turn))
        return outcome.result() if outcome.done() else "lost"

    def _on_busy(self, session: Session, turn: int) -> None:
        """Колонка не приняла announce/listen хода turn: выбросить запись прослушивания, снять ход."""
        recording = session.recording
        if recording is not None and recording.esp_turn == turn:
            session.recording = None
        self._end_turn(session, turn, "busy")

    def _end_turn(self, session: Session, esp_turn: int, outcome: Delivery) -> bool:
        """Заканчивает активный ход колонки esp_turn с итогом и сообщает арбитру. False — не активен."""
        if not session.end_turn(esp_turn, outcome):
            return False
        self._arbiter.on_turn_finished(session.device_id, esp_turn)
        return True
