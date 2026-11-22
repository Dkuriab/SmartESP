"""Основа хаба: общее состояние (сессии, номера ходов, фоновые отправки) и ходы ядра —
объявление и прослушивание (протокол 3) с итогом доставки."""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import replace
from typing import Any

from smartesp.contracts import Delivery, DeviceInfo

from .arbiter import Arbiter
from .messages import Played, cancel_turn
from .messages import announce as announce_frame
from .messages import listen as listen_frame
from .messages import update as update_frame
from .messages import volume as volume_frame
from .playback import close_audio, send_reply
from .session import ActiveTurn, Recording, Session
from .updates import UPDATE_PROTOCOL, UpdateStates

PROACTIVE_PROTOCOL = 3  # с этой версии колонка понимает listen и отвечает busy
REPLY_GRACE_S = 15.0  # нет playback_done за длительность звука + столько секунд — объявление потеряно
LISTEN_WAIT_S = 30.0  # сколько ждать playback_done хода перед listen
LISTEN_ORIGIN = "listen"  # Utterance.origin хода, начатого командой listen
DEFAULT_VOLUME = 50  # %, как у прошивки по умолчанию
RECORD_TIMEOUT_S = 15.0  # запись для обучения: дольше фразы не ждём (колонка ушла, связь оборвалась)


async def _no_audio() -> AsyncIterator[bytes]:
    """Пустой ответ: reply_start + reply_end — колонка перестаёт ждать и возвращается к слову."""
    for chunk in list[bytes]():
        yield chunk


logger = logging.getLogger(__name__)


class CoreTurns:
    """Основа DeviceHub: общее состояние хаба (его читает и hub.py) и ходы, которые начинает ядро.

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
        self._background: set[asyncio.Task[object]] = set()  # отправки, которых никто не ждёт
        self._volumes: dict[str, int] = {}  # громкость колонок из настроек, %
        self._updates = UpdateStates()  # обновления по воздуху: что отправлено и что ответила колонка
        self._updates.on_change = lambda device, progress: self._publish(
            "device_update", {"device_id": device, **vars(progress)}
        )

    def supports_proactive(self, device_id: str) -> bool:
        """True, если колонка подключена и её протокол ≥ 3."""
        session = self._sessions.get(device_id)
        return session is not None and session.protocol >= PROACTIVE_PROTOCOL

    def is_busy(self, device_id: str) -> bool:
        """True, если колонка подключена и на ней идёт ход или запись хаба."""
        session = self._sessions.get(device_id)
        return session is not None and not session.is_idle()

    def last_active_device(self) -> str | None:
        """Колонка последнего принятого хода (по слову или прослушиванию), если подключена."""
        return self._last_active if self._last_active in self._sessions else None

    def proactive_devices(self) -> list[str]:
        """Подключённые колонки с протоколом ≥ 3, по имени (имя — device_name хаба)."""
        found = [d for d, session in self._sessions.items() if session.protocol >= PROACTIVE_PROTOCOL]
        return sorted(found, key=lambda device_id: (self.device_name(device_id), device_id))

    def played_bytes(self, device_id: str, turn: int) -> int | None:
        """Сколько байт звука ответа хода хаба turn уже прозвучало: по событиям played, а у колонки
        без них — по оценке темпа. None — ход не активен или его ответ ещё не начат."""
        session = self._sessions.get(device_id)
        progress = session.progress if session is not None and session.is_live(turn) else None
        return progress.position() if progress is not None and progress.turn_id == turn else None

    def device_name(self, device_id: str) -> str:
        """Имя колонки; хаб переопределяет его именами из настроек."""
        return device_id

    async def announce(self, device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        """announce → reply_start → звук → reply_end новым ходом ядра; ждёт итог.

        Сигнал «внимание» колонка играет сама, только приняв announce: ядро tone не шлёт, иначе
        занятая колонка сыграла бы его посреди разговора, ещё до своего ответа busy.

        Колонка не подключена, протокол < 3 или хаб останавливается — "lost" без кадров; у хаба на
        ней идёт ход — "busy". Поток audio закрывается при любом выходе. Отмена посреди звука
        снимает ход и шлёт колонке cancel_turn.
        """
        session = self._idle_session(device_id)
        if session is None or not self._accepting:
            await close_audio(audio)
            return "busy" if session is None and self.supports_proactive(device_id) else "lost"
        turn_id, esp_turn = next(self._turn_ids), session.next_core_turn()
        session.active = ActiveTurn(turn_id, esp_turn)
        outcome = session.outcome(turn_id)
        assert outcome is not None  # ход только что стал активным
        sending = asyncio.create_task(self._send_announcement(session, turn_id, esp_turn, audio))
        try:
            await asyncio.wait((sending, outcome), return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:  # колонка без reply_end ждала бы вечно — освобождаем её
            if self._end_turn(session, esp_turn, "lost"):
                self._spawn(session.send(cancel_turn(esp_turn)), f"cancel_turn to {device_id}")
            raise
        finally:
            sending.cancel()  # итог уже известен (busy, обрыв…) — дальше звук не нужен
            (sent,) = await asyncio.gather(sending, return_exceptions=True)
        if outcome.done():
            return outcome.result()
        if isinstance(sent, BaseException):
            logger.warning("announcement audio for %s failed", device_id, exc_info=sent)
            return await self._give_up(session, esp_turn, outcome)
        try:  # sent — сколько секунд звука колонке ещё играть
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

    def volume_of(self, device_id: str) -> int:
        """Громкость колонки из настроек, % (не задана — как у прошивки по умолчанию)."""
        return self._volumes.get(device_id, DEFAULT_VOLUME)

    def set_volumes(self, volumes: dict[str, int]) -> None:
        """Громкость колонок из настроек; подключённым с изменившейся — сразу кадр volume."""
        old, self._volumes = self._volumes, dict(volumes)
        for device_id, session in self._sessions.items():
            if self.volume_of(device_id) != old.get(device_id, DEFAULT_VOLUME):
                self._send_volume(session)

    def _with_state(self, devices: list[DeviceInfo]) -> list[DeviceInfo]:
        """Сведения о колонках с громкостью из настроек и последним обновлением по воздуху."""
        return [
            replace(d, update=self._updates.get(d.device_id), volume=self.volume_of(d.device_id))
            for d in devices
        ]

    def _send_volume(self, session: Session) -> None:
        """Громкость — колонке (при подключении: колонка после перезагрузки её не помнит)."""
        frame = volume_frame(self.volume_of(session.device_id))
        self._spawn(session.send(frame), f"volume to {session.device_id}")

    def _publish(self, kind: str, data: dict[str, object]) -> None:
        """Событие для интерфейса; хаб переопределяет (у него приёмник событий)."""

    def supports_update(self, device_id: str) -> bool:
        """Колонка подключена и умеет обновляться по воздуху (протокол ≥ 4, прошивка 0.5.0+)."""
        session = self._sessions.get(device_id)
        return session is not None and session.protocol >= UPDATE_PROTOCOL

    async def send_update(self, device_id: str, payload: dict[str, object]) -> bool:
        """Шлёт колонке команду update (см. messages.update); False — не умеет или не подключена."""
        session = self._sessions.get(device_id)
        if session is None or not self.supports_update(device_id):
            return False
        if not await session.send(update_frame(payload)):
            return False
        self._updates.sent(device_id, str(payload.get("what", "")), int(payload.get("size", 0)))  # type: ignore[call-overload]
        return True

    async def record(self, device_id: str, timeout_s: float = RECORD_TIMEOUT_S) -> bytes | None:
        """Пишет одну фразу с колонки мимо разговора (для обучения): listen новым ходом ядра, колонка
        пикает и слушает до паузы; ход кончается без ответа. Возвращает PCM 16 кГц моно s16le или
        None — колонка не подключена, протокол < 3, занята, речи не было или не дождались timeout_s.
        """
        session = self._idle_session(device_id)
        if session is None or not self._accepting:
            return None
        turn_id, esp_turn = next(self._turn_ids), session.next_core_turn()
        captured: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        session.recording = Recording(esp_turn, self._clock(), turn_id=turn_id, capture=captured)
        session.active = ActiveTurn(turn_id, esp_turn)
        self._arbiter.on_turn_started(device_id, esp_turn)
        outcome = session.outcome(turn_id)
        if outcome is None or not await session.send(listen_frame(esp_turn), turn_id):
            return None
        # ход кончится раньше записи (busy, обрыв, отмена) — ждать нечего
        done, _ = await asyncio.wait(
            (captured, outcome), timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED
        )
        if captured.done():
            return captured.result() or None
        if not done and self._end_turn(session, esp_turn, "lost"):
            self._spawn(session.send(cancel_turn(esp_turn)), f"cancel_turn to {device_id}")
        return None

    def _captured(self, session: Session, recording: Recording, pcm: bytes) -> bool:
        """Запись для обучения: звук — ждущему record, ход кончается пустым ответом. Иначе False."""
        if recording.capture is None:
            return False
        if not recording.capture.done():
            recording.capture.set_result(pcm)
        if pcm and recording.turn_id is not None:
            reply = send_reply(session, recording.turn_id, _no_audio(), self._clock)
            self._spawn(reply, f"end of recording on {session.device_id}")
        return True

    async def listen_after(self, device_id: str, turn: int) -> None:
        """Ждёт playback_done хода хаба turn (не дольше LISTEN_WAIT_S), затем listen.

        Ход кончился иначе (перебили, отменили, busy, обрыв), колонка v2 или переподключилась —
        ничего не делает. Звать сразу после play: ход, уже доигранный к моменту вызова, не ждётся.
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

    def _spawn(self, coro: Coroutine[Any, Any, object], what: str) -> None:
        """Запускает отправку в фоне: зависшая колонка не должна тормозить хаб и других."""
        task = asyncio.create_task(coro)
        self._background.add(task)

        def done(t: asyncio.Task[object]) -> None:
            self._background.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("%s failed", what, exc_info=t.exception())

        task.add_done_callback(done)

    async def _send_announcement(
        self, session: Session, turn_id: int, esp_turn: int, audio: AsyncIterator[bytes]
    ) -> float:
        """Кадры объявления по порядку; возвращает, сколько секунд звука колонке ещё играть."""
        try:
            if await session.send(announce_frame(esp_turn), turn_id):
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

    def _on_played(self, session: Session, played: Played) -> None:
        """Колонка сообщила, сколько звука ответа активного хода доиграно (чужой ход — мимо)."""
        active, progress = session.active, session.progress
        if active is not None and progress is not None and active.esp_turn == played.turn:
            if progress.turn_id == active.turn_id:
                progress.played = played.bytes

    def _end_turn(self, session: Session, esp_turn: int, outcome: Delivery) -> bool:
        """Заканчивает активный ход колонки esp_turn с итогом и сообщает арбитру. False — не активен."""
        if not session.end_turn(esp_turn, outcome):
            return False
        self._arbiter.on_turn_finished(session.device_id, esp_turn)
        return True
